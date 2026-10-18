"""Optional local Source asset and entity catalogs, using srctools."""

from pathlib import Path

from .backend import configured_path, require_game
from .project import Project
from .vmf import MapError


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
    FGD, _ = source_tools()
    path = configured_path(project, config, "fgd")
    if not path or not path.is_file():
        raise MapError("Configure the legacy CS:GO FGD path first")
    from srctools.filesys import RawFileSystem
    from srctools.fgd import FGDParseError

    try:
        fgd = FGD.parse(path.name, RawFileSystem(path.parent))
    except FGDParseError as exc:
        raise MapError(f"Cannot parse configured FGD: {exc}") from exc
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
            "source": str(path),
        }
    matches = sorted(
        (ent for ent in fgd if query.casefold() in ent.classname.casefold()),
        key=lambda ent: ent.classname,
    )
    return {
        "source": str(path),
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
    }


def assets(
    project: Project,
    config: dict,
    kind: str = "material",
    query: str = "",
    limit: int = 100,
) -> dict:
    if kind not in ("material", "model") or not 1 <= limit <= 1000:
        raise MapError("kind must be material or model; limit between 1 and 1000")
    _, VPK = source_tools()
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
