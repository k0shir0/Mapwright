"""Optional local Source asset and entity catalogs, using srctools."""

from pathlib import Path

from .backend import require_game, fgd_paths
from .project import Project
from .vmf import MapError
from .streams import file_digest


def game_filesystem(game):
    source_tools()
    from srctools.game import Game
    from srctools.filesys import FileSystemChain, RawFileSystem, VPKFileSystem

    try:
        return Game(game).get_filesystem()
    except KeyError:
        # Minimal gameinfo fixtures and older custom projects may omit SearchPaths.
        return FileSystemChain(
            *(VPKFileSystem(p) for p in sorted(game.glob("*_dir.vpk"))),
            RawFileSystem(game),
        )


def source_tools():
    try:
        from srctools.fgd import FGD
        from srctools.vpk import VPK
    except ImportError as exc:
        raise MapError(
            'Install the source extra: python -m pip install -e ".[source]"'
        ) from exc
    return FGD, VPK


def entities(
    project: Project,
    config: dict,
    query: str = "",
    classname: str = "",
    limit: int = 100,
) -> dict:
    if not 1 <= limit <= 1000:
        raise MapError("limit must be between 1 and 1000")
    paths = fgd_paths(project, config)
    warnings = []
    fgd = entity_definitions(project, config, warnings)
    if classname:
        try:
            ent = fgd[classname]
        except KeyError as exc:
            raise MapError(f"Unknown FGD classname: {classname}") from exc

        def describe(view, defaults=False):
            result = []
            for key in view:
                value = view[key]
                row = {
                    "name": value.name,
                    "type": (
                        value.type.value if hasattr(value.type, "value") else value.type
                    ),
                    "description": value.desc,
                }
                if defaults:
                    row["default"] = value.default
                result.append(row)
            return result

        return {
            "classname": ent.classname,
            "type": ent.type.value,
            "description": ent.desc,
            "keyvalues": describe(ent.kv, True),
            "inputs": describe(ent.inp),
            "outputs": describe(ent.out),
            "source": [str(p) for p in paths] if len(paths) > 1 else str(paths[0]),
            "warnings": warnings,
        }
    matches = sorted(
        (ent for ent in fgd if query.casefold() in ent.classname.casefold()),
        key=lambda ent: ent.classname,
    )
    return {
        "source": [str(p) for p in paths] if len(paths) > 1 else str(paths[0]),
        "total": len(matches),
        "truncated": len(matches) > limit,
        "entities": [
            {
                "classname": ent.classname,
                "type": ent.type.value,
                "description": ent.desc,
            }
            for ent in matches[:limit]
        ],
        "warnings": warnings,
    }


def entity_definitions(project, config, warnings=None):
    FGD, _ = source_tools()
    paths = fgd_paths(project, config)
    if not paths or not all(p.is_file() for p in paths):
        raise MapError("Configure the legacy CS:GO FGD path first")
    from srctools.filesys import RawFileSystem
    from srctools.fgd import FGDParseError

    key = tuple(str(p) for p in paths)
    cached = project._catalogs.get(key)
    if cached is not None:
        model, dependencies, messages = cached
        if all(
            path.is_file() and file_digest(path) == revision
            for path, revision in dependencies.items()
        ):
            if warnings is not None:
                warnings.extend(messages)
            return model
    dependencies, messages = {}, []

    class TrackedFGD(FGD):
        def parse_file(self, filesystem, file, **options):
            path = (Path(filesystem.path) / file.path).resolve()
            dependencies[path] = file_digest(path)
            return super().parse_file(filesystem, file, **options)

    try:
        fgd = TrackedFGD()
        for path in paths:
            filesystem = RawFileSystem(path.parent)
            previous = dict(fgd.entities)
            fgd.parse_file(filesystem, filesystem[path.name], eval_bases=False)
            # Add-on FGDs repeat trigger_multiple/worldspawn. Preserve base fields
            # while letting the later file's keys override the same named key.
            for name, original in previous.items():
                current = fgd.entities.get(name)
                if current is not None and current is not original:
                    resolved = []
                    for base in current.bases:
                        if isinstance(base, str):
                            if base.casefold() not in fgd.entities:
                                messages.append(
                                    f"{current.classname}: addon base {base} is absent; retained existing class fields/bases. The editor uses the merged FGD generated by setup."
                                )
                                continue
                            base = fgd[base]
                        resolved.append(base)
                    bases = {
                        base.classname if not isinstance(base, str) else base: base
                        for base in [*original.bases, *resolved]
                    }
                    current.bases = list(bases.values())
                    for field in ("keyvalues", "inputs", "outputs"):
                        setattr(
                            current,
                            field,
                            {**getattr(original, field), **getattr(current, field)},
                        )
                    current.kv_order = list(
                        dict.fromkeys([*original.kv_order, *current.kv_order])
                    )
            fgd.apply_bases()
    except FGDParseError as exc:
        raise MapError(f"Cannot parse configured FGD: {exc}") from exc
    if not all(
        path.is_file() and file_digest(path) == revision
        for path, revision in dependencies.items()
    ):
        raise MapError("FGD inputs changed during parsing; retry")
    if warnings is not None:
        warnings.extend(messages)
    project._catalogs.put(key, (fgd, dependencies, messages))
    return fgd


def assets(
    project: Project,
    config: dict,
    kind: str = "material",
    query: str = "",
    limit: int = 100,
) -> dict:
    if kind not in ("material", "model") or not 1 <= limit <= 1000:
        raise MapError("kind must be material or model; limit between 1 and 1000")
    game = require_game(project, config)
    folder, suffix = ("materials", ".vmt") if kind == "material" else ("models", ".mdl")
    matches = {}

    def add(name: str, source: str):
        name = name.replace("\\", "/")
        if (
            name.casefold().startswith(folder + "/")
            and name.casefold().endswith(suffix)
            and query.casefold() in name.casefold()
        ):
            reference = name[len(folder) + 1 :]
            if kind == "material":
                reference = reference[:-4]
            else:
                reference = name
            matches.setdefault(reference, source)

    filesystem = game_filesystem(game)
    for file in filesystem.walk_folder(folder):
        add(file.path, str(filesystem.get_system(file).path))
    archives = [
        str(provider.path)
        for provider, _ in filesystem.systems
        if str(provider.path).lower().endswith(".vpk")
    ]
    names = sorted(matches)
    return {
        "kind": kind,
        "total": len(names),
        "truncated": len(names) > limit,
        "assets": [{"name": name, "source": matches[name]} for name in names[:limit]],
        "scope": str(game),
        "archives": archives,
        "limitations": "Indexes configured gameinfo search paths and VPK directories through srctools. This does not prove rendering or inspect material dependency content.",
    }
