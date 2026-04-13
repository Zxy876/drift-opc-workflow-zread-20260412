from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
import shutil

import pymeshlab
import trimesh

logger = logging.getLogger("scan-mesh-cleaner")
print("🔥 NEW SCAN WORKER LOADED 🔥", flush=True)


@dataclass
class MeshCleanConfig:
    target_faces: int = 20000
    isolated_piece_min_diameter_pct: float = 3.0


def _percentage_param(value: float):
    if hasattr(pymeshlab, "PercentageValue"):
        return pymeshlab.PercentageValue(float(value))
    if hasattr(pymeshlab, "Percentage"):
        return pymeshlab.Percentage(float(value))
    return float(value)


def _try_filters(mesh_set: pymeshlab.MeshSet, filter_calls: list[tuple[str, dict]]) -> str:
    last_error: Exception | None = None
    for name, kwargs in filter_calls:
        try:
            method = getattr(mesh_set, name, None)
            if callable(method):
                method(**kwargs)
                return name
        except Exception as exc:  # pragma: no cover - pymeshlab runtime variants
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("no compatible pymeshlab filter found")


def _save_mesh_with_fallback(mesh_set: pymeshlab.MeshSet, output_path: Path) -> tuple[Path, str]:
    mesh = mesh_set.current_mesh()
    exported_mesh = trimesh.Trimesh(
        vertices=mesh.vertex_matrix(),
        faces=mesh.face_matrix(),
        process=False,
    )
    scene = trimesh.Scene(exported_mesh)
    scene.export(str(output_path))
    return output_path, output_path.suffix.lower()


def _load_scene_preserve_materials(input_path: Path) -> trimesh.Scene:
    loaded = trimesh.load(str(input_path), process=False, force="scene")
    if isinstance(loaded, trimesh.Scene):
        return loaded.copy()
    if isinstance(loaded, trimesh.Trimesh):
        scene = trimesh.Scene()
        scene.add_geometry(loaded.copy(), geom_name=input_path.stem)
        return scene
    raise ValueError(f"unsupported mesh type: {type(loaded).__name__}")


def _scene_face_counts(scene: trimesh.Scene) -> tuple[int, int]:
    vertices = 0
    faces = 0
    for geometry in scene.geometry.values():
        if isinstance(geometry, trimesh.Trimesh):
            vertices += int(len(geometry.vertices))
            faces += int(len(geometry.faces))
    return vertices, faces


def _scene_has_texture_materials(scene: trimesh.Scene) -> bool:
    for geometry in scene.geometry.values():
        visual = getattr(geometry, "visual", None)
        if visual is None:
            continue
        material = getattr(visual, "material", None)
        uv = getattr(visual, "uv", None)
        if uv is not None:
            return True
        if material is None:
            continue
        if getattr(material, "image", None) is not None:
            return True
        if getattr(material, "baseColorTexture", None) is not None:
            return True
        if getattr(material, "name", None):
            return True
    return False


def _parse_obj_mtllib(obj_path: Path) -> list[Path]:
    mtllib_paths: list[Path] = []
    try:
        for line in obj_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("mtllib "):
                rel = stripped[len("mtllib "):].strip()
                if rel:
                    candidate = (obj_path.parent / rel).resolve()
                    if candidate.exists():
                        mtllib_paths.append(candidate)
    except Exception as exc:  # pragma: no cover - debug guard
        logger.warning("failed to parse mtllib from obj=%s err=%s", obj_path, exc)
    return mtllib_paths


def _parse_mtl_texture_refs(mtl_path: Path) -> dict[str, Path]:
    refs: dict[str, Path] = {}
    current_material: str | None = None
    try:
        for line in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lower = stripped.lower()
            if lower.startswith("newmtl "):
                current_material = stripped[len("newmtl "):].strip()
                continue
            if not lower.startswith("map_kd "):
                continue

            tokens = stripped.split()
            if len(tokens) < 2:
                continue
            texture_rel = tokens[-1]
            texture_path = (mtl_path.parent / texture_rel).resolve()
            if not texture_path.exists():
                continue
            if current_material:
                refs[current_material] = texture_path
            if "__default__" not in refs:
                refs["__default__"] = texture_path
    except Exception as exc:  # pragma: no cover - debug guard
        logger.warning("failed to parse mtl=%s err=%s", mtl_path, exc)
    return refs


def _build_obj_texture_map(obj_path: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for mtl_path in _parse_obj_mtllib(obj_path):
        mapping.update(_parse_mtl_texture_refs(mtl_path))
    return mapping


def _hydrate_missing_texture_images(scene: trimesh.Scene, input_path: Path) -> int:
    if input_path.suffix.lower() != ".obj":
        return 0

    texture_map = _build_obj_texture_map(input_path)
    if not texture_map:
        return 0

    hydrated = 0
    for name, geometry in scene.geometry.items():
        visual = getattr(geometry, "visual", None)
        uv = getattr(visual, "uv", None)
        material = getattr(visual, "material", None)
        has_image = material is not None and getattr(material, "image", None) is not None
        logger.info(
            "texture-check geom=%s visual=%s has_uv=%s has_image=%s material=%s",
            name,
            type(visual).__name__ if visual is not None else "None",
            uv is not None,
            has_image,
            getattr(material, "name", None) if material is not None else None,
        )
        if uv is None or has_image:
            continue

        material_name = getattr(material, "name", None)
        texture_path = texture_map.get(material_name) or texture_map.get("__default__")
        if texture_path is None:
            continue

        try:
            from PIL import Image

            image = Image.open(texture_path)
            new_material = trimesh.visual.material.SimpleMaterial(
                image=image,
                name=material_name or texture_path.stem,
            )
            geometry.visual = trimesh.visual.texture.TextureVisuals(
                uv=uv.copy(),
                material=new_material,
            )
            hydrated += 1
        except Exception as exc:  # pragma: no cover - runtime image backend variants
            logger.warning("failed to hydrate texture for geom=%s texture=%s err=%s", name, texture_path, exc)
    return hydrated


def _material_image_data(material) -> object | None:
    if material is None:
        return None

    image = getattr(material, "image", None)
    if image is not None:
        return image

    base_color_texture = getattr(material, "baseColorTexture", None)
    if base_color_texture is None:
        return None

    if isinstance(base_color_texture, (str, Path)):
        try:
            from PIL import Image

            texture_path = Path(base_color_texture).expanduser().resolve()
            if texture_path.exists():
                with Image.open(texture_path) as pil_image:
                    return pil_image.copy()
        except Exception as exc:  # pragma: no cover - runtime image backend variants
            logger.warning("failed to load baseColorTexture path=%s err=%s", base_color_texture, exc)
        return None

    return base_color_texture


def _ensure_pbr_materials(scene: trimesh.Scene) -> int:
    converted = 0
    for name, geometry in scene.geometry.items():
        visual = getattr(geometry, "visual", None)
        if visual is None:
            continue

        uv = getattr(visual, "uv", None)
        if uv is None:
            continue

        material = getattr(visual, "material", None)
        image_data = _material_image_data(material)
        if image_data is None:
            continue

        material_name = getattr(material, "name", None) if material is not None else None
        geometry.visual = trimesh.visual.texture.TextureVisuals(
            uv=uv.copy(),
            material=trimesh.visual.material.PBRMaterial(
                name=material_name or f"{name}_pbr",
                baseColorTexture=image_data,
                baseColorFactor=[255, 255, 255, 255],
                metallicFactor=0.0,
                roughnessFactor=1.0,
            ),
        )
        converted += 1

    return converted


def _scene_visual_debug(scene: trimesh.Scene) -> dict:
    geometry_count = int(len(scene.geometry))
    texture_geometry_count = 0
    image_material_count = 0

    for geometry in scene.geometry.values():
        visual = getattr(geometry, "visual", None)
        material = getattr(visual, "material", None) if visual is not None else None
        uv = getattr(visual, "uv", None) if visual is not None else None
        image = getattr(material, "image", None) if material is not None else None
        if uv is not None:
            texture_geometry_count += 1
        if image is not None:
            image_material_count += 1

    visual_type = "none"
    if texture_geometry_count > 0 and image_material_count > 0:
        visual_type = "texture"
    elif texture_geometry_count > 0:
        visual_type = "uv-only"
    elif geometry_count > 0:
        visual_type = "geometry-only"

    return {
        "visualType": visual_type,
        "geometryCount": geometry_count,
        "textureGeometryCount": texture_geometry_count,
        "imageMaterialCount": image_material_count,
    }


def _log_scene_texture_details(scene: trimesh.Scene, stage: str) -> dict:
    geometry_count = int(len(scene.geometry))
    textured_geometry_count = 0
    has_any_image = False

    logger.info("texture-debug stage=%s geometryCount=%s", stage, geometry_count)

    for name, geometry in scene.geometry.items():
        visual = getattr(geometry, "visual", None)
        uv = getattr(visual, "uv", None) if visual is not None else None
        material = getattr(visual, "material", None) if visual is not None else None
        image = getattr(material, "image", None) if material is not None else None
        image_shape = getattr(image, "shape", None) if image is not None else None

        logger.info(
            "texture-debug geom=%s visualType=%s hasUv=%s hasMaterial=%s hasImage=%s imageShape=%s",
            name,
            type(visual).__name__ if visual is not None else "None",
            uv is not None,
            material is not None,
            image is not None,
            image_shape,
        )

        if uv is not None and image is None:
            logger.warning("texture-debug geom=%s UV present but NO IMAGE", name)

        if image is not None:
            textured_geometry_count += 1
            has_any_image = True

    return {
        "geometryCount": geometry_count,
        "texturedGeometryCount": textured_geometry_count,
        "hasAnyImage": has_any_image,
    }


def clean_mesh(
    input_path: str | Path,
    output_path: str | Path,
    config: MeshCleanConfig | None = None,
) -> dict:
    cfg = config or MeshCleanConfig()
    src = Path(input_path).expanduser().resolve()
    dst = Path(output_path).expanduser().resolve()

    if not src.exists():
        raise FileNotFoundError(f"input mesh not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Highest-priority material protection for native GLB scans: keep file byte-identical.
    if src.suffix.lower() == ".glb":
        shutil.copy2(src, dst)
        preserved_scene = _load_scene_preserve_materials(src)
        has_texture = _scene_has_texture_materials(preserved_scene)
        input_vertices, input_faces = _scene_face_counts(preserved_scene)
        visual_debug = _scene_visual_debug(preserved_scene)
        texture_summary = _log_scene_texture_details(preserved_scene, stage="native-glb-copy")
        return {
            "inputPath": str(src),
            "outputPath": str(dst),
            "inputVertices": input_vertices,
            "inputFaces": input_faces,
            "outputVertices": input_vertices,
            "outputFaces": input_faces,
            "hasTexture": has_texture,
            "texturePreserved": True,
            "enteredGeometryFallback": False,
            "visualType": visual_debug["visualType"],
            "geometryCount": visual_debug["geometryCount"],
            "texturedGeometryCount": texture_summary["texturedGeometryCount"],
            "hasAnyImage": texture_summary["hasAnyImage"],
            "targetFaces": int(cfg.target_faces),
            "outputFormat": dst.suffix.lower(),
            "filters": {
                "isolatedPieceRemoval": "skipped_native_glb_copy",
                "duplicateVertices": "skipped_native_glb_copy",
                "decimation": "skipped_native_glb_copy",
            },
        }

    preserved_scene = _load_scene_preserve_materials(src)
    hydrated_texture_count = _hydrate_missing_texture_images(preserved_scene, src)
    pbr_material_count = _ensure_pbr_materials(preserved_scene)
    input_vertices, input_faces = _scene_face_counts(preserved_scene)
    has_texture = _scene_has_texture_materials(preserved_scene)
    visual_debug = _scene_visual_debug(preserved_scene)

    if has_texture:
        texture_summary = _log_scene_texture_details(preserved_scene, stage="pre-export-textured")
        glb_data = preserved_scene.export(file_type="glb")
        dst.write_bytes(glb_data)
        output_vertices, output_faces = _scene_face_counts(preserved_scene)
        return {
            "inputPath": str(src),
            "outputPath": str(dst),
            "inputVertices": input_vertices,
            "inputFaces": input_faces,
            "outputVertices": output_vertices,
            "outputFaces": output_faces,
            "hasTexture": True,
            "texturePreserved": True,
            "enteredGeometryFallback": False,
            "visualType": visual_debug["visualType"],
            "geometryCount": visual_debug["geometryCount"],
            "texturedGeometryCount": texture_summary["texturedGeometryCount"],
            "hasAnyImage": texture_summary["hasAnyImage"],
            "hydratedTextureCount": hydrated_texture_count,
            "pbrMaterialCount": pbr_material_count,
            "targetFaces": int(cfg.target_faces),
            "outputFormat": dst.suffix.lower(),
            "filters": {
                "isolatedPieceRemoval": "skipped_preserve_materials",
                "duplicateVertices": "skipped_preserve_materials",
                "decimation": "skipped_preserve_materials",
            },
        }

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(src))

    mesh = ms.current_mesh()
    isolated_filter = _try_filters(
        ms,
        [
            (
                "remove_isolated_pieces_wrt_diameter",
                {"mincomponentdiag": _percentage_param(cfg.isolated_piece_min_diameter_pct)},
            ),
            (
                "meshing_remove_connected_component_by_diameter",
                {"mincomponentdiag": _percentage_param(cfg.isolated_piece_min_diameter_pct)},
            ),
        ],
    )

    duplicate_filter = _try_filters(
        ms,
        [
            ("remove_duplicate_vertices", {}),
            ("meshing_remove_duplicate_vertices", {}),
        ],
    )

    decimation_filter = _try_filters(
        ms,
        [
            (
                "simplification_quadric_edge_collapse_decimation",
                {
                    "targetfacenum": int(cfg.target_faces),
                    "preservenormal": True,
                    "preserveboundary": True,
                    "preservetopology": True,
                    "optimalplacement": True,
                },
            ),
            (
                "meshing_decimation_quadric_edge_collapse",
                {
                    "targetfacenum": int(cfg.target_faces),
                    "preservenormal": True,
                    "preserveboundary": True,
                    "preservetopology": True,
                    "optimalplacement": True,
                },
            ),
        ],
    )

    actual_output_path, output_format = _save_mesh_with_fallback(ms, dst)

    out_mesh = ms.current_mesh()
    output_vertices = int(out_mesh.vertex_number())
    output_faces = int(out_mesh.face_number())
    texture_summary = _log_scene_texture_details(preserved_scene, stage="geometry-fallback")

    return {
        "inputPath": str(src),
        "outputPath": str(actual_output_path),
        "inputVertices": input_vertices,
        "inputFaces": input_faces,
        "outputVertices": output_vertices,
        "outputFaces": output_faces,
        "hasTexture": False,
        "texturePreserved": False,
        "enteredGeometryFallback": True,
        "visualType": "geometry-only",
        "geometryCount": int(len(preserved_scene.geometry)),
        "texturedGeometryCount": texture_summary["texturedGeometryCount"],
        "hasAnyImage": texture_summary["hasAnyImage"],
        "hydratedTextureCount": hydrated_texture_count,
        "pbrMaterialCount": pbr_material_count,
        "targetFaces": int(cfg.target_faces),
        "outputFormat": output_format,
        "filters": {
            "isolatedPieceRemoval": isolated_filter,
            "duplicateVertices": duplicate_filter,
            "decimation": decimation_filter,
        },
    }


def clean_scan_to_glb(
    input_path: str | Path,
    output_path: str | Path,
    config: MeshCleanConfig | None = None,
) -> dict:
    return clean_mesh(input_path=input_path, output_path=output_path, config=config)
