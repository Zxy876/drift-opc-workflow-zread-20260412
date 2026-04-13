from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("assembly-builder")

ASSET_MAP = {
    "pocket": ("cyber_pocket.glb",),
    "collar": ("tech_collar.obj", "tech_collar.glb"),
    "buckle": ("buckle.glb",),
    "belt": ("buckle.glb",),
}


def _assets_dir() -> Path:
    configured = os.getenv("ASSEMBLY_ASSETS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "assets").resolve()


def _apply_pink_pbr(mesh: trimesh.Trimesh) -> None:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[255, 20, 147, 255]
        )
    )


def _create_fallback_box(extents: tuple[float, float, float], position: np.ndarray) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    _apply_pink_pbr(mesh)
    mesh.apply_translation(position)
    return mesh


def _resolve_asset_file(component: dict, assets_dir: Path) -> Path | None:
    searchable = json.dumps(component, ensure_ascii=False, default=str).lower()
    for keyword, file_names in ASSET_MAP.items():
        if keyword in searchable:
            for file_name in file_names:
                candidate = assets_dir / file_name
                if candidate.exists():
                    return candidate
            # Return the first expected file for clearer warning messages when all are missing.
            return assets_dir / file_names[0]
    return None


def _extract_mesh(loaded: object) -> trimesh.Trimesh:
    if isinstance(loaded, trimesh.Trimesh):
        return loaded.copy()

    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError("asset scene has no geometry")

        dumped = loaded.dump(concatenate=True)
        if isinstance(dumped, trimesh.Trimesh):
            return dumped

        if isinstance(dumped, list):
            meshes = [item for item in dumped if isinstance(item, trimesh.Trimesh) and not item.is_empty]
            if not meshes:
                raise ValueError("asset scene dump contains no mesh")
            return trimesh.util.concatenate(meshes)

    raise ValueError(f"unsupported asset type: {type(loaded).__name__}")


def _load_asset_mesh(component: dict, target_size: float, assets_dir: Path) -> trimesh.Trimesh | None:
    asset_file = _resolve_asset_file(component, assets_dir)
    if asset_file is None:
        logger.warning("No asset mapping matched for component=%s; fallback box will be used", component)
        return None

    if not asset_file.exists():
        logger.warning("Mapped asset file is missing: %s; fallback box will be used", asset_file)
        return None

    try:
        loaded = trimesh.load(str(asset_file), force="scene")
        mesh = _extract_mesh(loaded)
        if mesh.is_empty:
            raise ValueError("loaded asset mesh is empty")

        # Force asset geometry to local origin before any scale/placement to avoid offset drift.
        mesh.vertices -= np.array(mesh.bounding_box.centroid, dtype=float)

        max_extent = float(np.max(mesh.extents))
        if max_extent <= 0:
            raise ValueError("loaded asset has non-positive extents")

        scale_factor = float(target_size) / max_extent
        mesh.apply_scale(scale_factor)
        return mesh
    except Exception as exc:
        logger.warning("Failed to load/scale asset for component=%s file=%s; fallback to box. reason=%s", component, asset_file, exc)
        return None


def _load_base_geometry(base_model_path: str | None) -> tuple[trimesh.Scene, dict]:
    scene = trimesh.Scene()
    stats = {
        "baseModelLoaded": False,
        "baseGeometryCount": 0,
    }

    if not base_model_path:
        return scene, stats

    base_path = Path(base_model_path).expanduser().resolve()
    if not base_path.exists():
        stats["baseModelMissing"] = str(base_path)
        return scene, stats

    loaded = trimesh.load(str(base_path), force="scene")
    if isinstance(loaded, trimesh.Scene):
        # Preserve the original scene graph and material/image bindings from the scanned model.
        scene = loaded.copy()
    else:
        scene.add_geometry(loaded.copy(), geom_name="base_mesh")

    if scene.geometry:
        base_center = np.array(scene.centroid, dtype=float)
        if not np.all(np.isfinite(base_center)):
            min_bound, max_bound = _bounds(scene)
            base_center = (min_bound + max_bound) / 2
        scene.apply_transform(trimesh.transformations.translation_matrix(-base_center))
        stats["baseCenteringApplied"] = True
        stats["baseCenterOffset"] = base_center.tolist()

    stats["baseModelLoaded"] = True
    stats["baseGeometryCount"] = len(scene.geometry)
    stats["baseModelPath"] = str(base_path)
    return scene, stats


def _bounds(scene: trimesh.Scene) -> tuple[np.ndarray, np.ndarray]:
    if scene.geometry:
        bounds = scene.bounds
        return np.array(bounds[0], dtype=float), np.array(bounds[1], dtype=float)
    return np.array([-0.25, -0.25, -0.25], dtype=float), np.array([0.25, 0.25, 0.25], dtype=float)


def _scene_extents_and_centroid(scene: trimesh.Scene) -> tuple[np.ndarray, np.ndarray]:
    if not scene.geometry:
        return np.array([0.4, 0.4, 0.4], dtype=float), np.array([0.0, 0.0, 0.0], dtype=float)

    extents = np.array(scene.extents, dtype=float)
    centroid = np.array(scene.centroid, dtype=float)

    if not np.all(np.isfinite(extents)) or float(np.max(extents)) <= 0:
        min_bound, max_bound = _bounds(scene)
        extents = np.maximum(max_bound - min_bound, np.array([0.4, 0.4, 0.4]))

    if not np.all(np.isfinite(centroid)):
        min_bound, max_bound = _bounds(scene)
        centroid = (min_bound + max_bound) / 2

    return extents, centroid


def _is_attachable(component: dict) -> bool:
    cid = str(component.get("id", "")).lower()
    category = str(component.get("category", "")).lower()
    panel_role = str(component.get("panelRole", "")).lower()
    keywords = ("pocket", "collar", "lapel", "cuff", "sleeve", "hood", "panel")
    text = " ".join([cid, category, panel_role])
    return any(keyword in text for keyword in keywords)


def _module_extents(component: dict, base_max_extent: float) -> tuple[float, float, float]:
    category = str(component.get("category", "")).lower()
    base_unit = max(0.08, float(base_max_extent * 0.15))
    if "pocket" in category:
        return (base_unit * 0.95, base_unit * 0.45, base_unit * 0.85)
    if "collar" in category or "lapel" in category:
        return (base_unit * 1.2, base_unit * 0.35, base_unit * 0.65)
    if "sleeve" in category:
        return (base_unit * 1.35, base_unit * 0.5, base_unit * 0.7)
    return (base_unit * 0.9, base_unit * 0.4, base_unit * 0.7)


def _tight_fit_position(
    component: dict,
    extents: np.ndarray,
    target_size: float,
    index: int,
    total_count: int,
) -> np.ndarray:
    text = " ".join(
        [
            str(component.get("id", "")).lower(),
            str(component.get("name", "")).lower(),
            str(component.get("category", "")).lower(),
            str(component.get("panelRole", "")).lower(),
        ]
    )
    half = extents / 2.0
    margin = max(0.03, target_size * 0.5)
    x = 0.0
    y = 0.0
    z = half[2] + margin

    if "collar" in text or "hood" in text or "lapel" in text:
        y = half[1] + margin
        z = half[2] * 0.35 + margin * 0.2
    elif "pocket" in text:
        y = -half[1] * 0.2
        if "left" in text:
            x = -half[0] * 0.38
        elif "right" in text:
            x = half[0] * 0.38
        else:
            pocket_slot = (index % max(1, total_count)) - (max(1, total_count) - 1) / 2.0
            x = pocket_slot * max(target_size * 0.75, half[0] * 0.22)
    elif "belt" in text or "buckle" in text:
        y = -half[1] * 0.48
        z = half[2] + margin * 0.35
    elif "sleeve" in text or "cuff" in text:
        x = (-1 if ("left" in text or index % 2 == 0) else 1) * (half[0] + margin)
        y = half[1] * 0.1
        z = half[2] * 0.15
    elif "back" in text:
        z = -(half[2] + margin)
    else:
        fallback_slot = (index % max(1, total_count)) - (max(1, total_count) - 1) / 2.0
        x = fallback_slot * max(target_size * 0.65, half[0] * 0.18)
        y = ((index % 2) - 0.5) * half[1] * 0.25

    return np.array([x, y, z], dtype=float)


def build_assembly_scene(
    task_id: str,
    dsl: dict,
    base_model_path: str | None,
    output_dir: str | Path,
) -> dict:
    scene, stats = _load_base_geometry(base_model_path)
    assets_dir = _assets_dir()

    extents, center = _scene_extents_and_centroid(scene)

    components = dsl.get("components") if isinstance(dsl, dict) else []
    if not isinstance(components, list):
        components = []

    logger.info("DSL components length=%d", len(components))
    logger.info("DSL components payload=%s", json.dumps(components, ensure_ascii=False, default=str))
    if not components:
        logger.warning(
            "DSL components are empty; upstream GPT may not have produced modular components. task_id=%s",
            task_id,
        )

    attachable = [component for component in components if isinstance(component, dict) and _is_attachable(component)]
    if not attachable:
        attachable = [component for component in components if isinstance(component, dict)][:5]

    module_count = 0
    base_max_extent = float(max(extents[0], extents[1], extents[2]))

    for index, component in enumerate(attachable):
        ext = _module_extents(component, base_max_extent)
        target_size = float(max(ext))
        position = _tight_fit_position(
            component,
            extents=extents,
            target_size=target_size,
            index=index,
            total_count=len(attachable),
        )

        mesh = _load_asset_mesh(component, target_size=target_size, assets_dir=assets_dir)
        if mesh is None:
            mesh = _create_fallback_box(ext, position)
        else:
            try:
                centroid = np.array(mesh.bounding_box.centroid, dtype=float)
                mesh.apply_translation(position - centroid)
            except Exception as exc:
                logger.warning("Failed to place asset mesh for component=%s; fallback to box. reason=%s", component, exc)
                mesh = _create_fallback_box(ext, position)

        component_id = str(component.get("id") or f"module_{index}")
        scene.add_geometry(mesh, geom_name=f"module_{component_id}")
        module_count += 1

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"final_assembly_{task_id}.glb"

    scene.export(str(output_path))

    stats.update(
        {
            "moduleCount": module_count,
            "totalGeometryCount": len(scene.geometry),
            "outputPath": str(output_path),
            "baseExtents": extents.tolist(),
            "baseCenter": center.tolist(),
            "layoutMode": "tight-fit",
            "assetsDir": str(assets_dir),
        }
    )

    return {
        "outputPath": str(output_path),
        "stats": stats,
    }
