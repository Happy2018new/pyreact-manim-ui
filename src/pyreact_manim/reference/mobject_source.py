"""Construct real upstream Text/Tex with explicit font and TeX provenance."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import subprocess
from threading import RLock

from .fonts import resolve_system_font, validate_font_coverage


_TEX_LOCK = RLock()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tool_info(name):
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError("Real LaTeX export requires %s on PATH; see tools/reference/LATEX.md" % name)
    result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Cannot inspect %s: %s" % (name, result.stderr.strip()))
    return {"executable": str(Path(executable).resolve()), "sha256": _sha256(executable),
            "version": result.stdout.splitlines()[0]}


def tex_toolchain():
    """Read installed tools only; never install a distribution or packages."""
    latex, dvisvgm = _tool_info("latex"), _tool_info("dvisvgm")
    miktex = "miktex" in latex["version"].lower()
    return {"latex": latex, "dvisvgm": dvisvgm, "miktex": miktex,
            "command_adapter": {"scope": "manimlib.utils.tex_file_writing subprocess calls only",
                                "remove_miktex_latex_flag": "-no-pdf" if miktex else None,
                                "tex_input_path": "basename with temporary source directory as cwd (Windows 8.3 tilde compatibility)",
                                "automatic_package_installation": False,
                                "shell_escape": False, "subprocess_timeout_seconds": 90}}


class _TexSubprocess:
    """Module-local proxy: leave process-global subprocess.run untouched."""

    def __init__(self, original, toolchain):
        self.original = original
        self.toolchain = toolchain

    def __getattr__(self, name):
        return getattr(self.original, name)

    def run(self, arguments, **kwargs):
        command = list(arguments)
        tool = Path(command[0]).stem.lower()
        if tool in ("latex", "dvisvgm"):
            command[0] = self.toolchain[tool]["executable"]
        if tool == "latex":
            source_path = Path(command[-1]).resolve()
            kwargs["cwd"] = str(source_path.parent)
            command[-1] = source_path.name
            if self.toolchain["miktex"]:
                # MiKTeX latex already outputs DVI and rejects TeX Live's -no-pdf.
                command = [part for part in command if part != "-no-pdf"]
                command[1:1] = ["-disable-installer", "-disable-write18"]
            else:
                command[1:1] = ["-no-shell-escape"]
        kwargs.setdefault("timeout", 90)
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = self.original.run(command, **kwargs)
        if tool == "latex" and result.returncode:
            log_path = source_path.with_suffix(".log")
            if not log_path.exists():
                log_path = source_path.parent / "texput.log"
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError("LaTeX compilation failed (exit %d):\n%s\n%s\n%s" %
                               (result.returncode, result.stdout or "", result.stderr or "", log[-12000:]))
        if tool == "dvisvgm" and result.returncode:
            stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr
            raise RuntimeError("dvisvgm failed: " + (stderr or "no diagnostic output").strip())
        return result


@contextmanager
def native_tex_environment(toolchain=None):
    """Adapt host command flags, without modifying Tex or its generated geometry."""
    from manimlib.utils import tex_file_writing

    toolchain = toolchain if toolchain is not None else tex_toolchain()
    with _TEX_LOCK:
        original = tex_file_writing.subprocess
        tex_file_writing.subprocess = _TexSubprocess(original, toolchain)
        try:
            yield toolchain
        finally:
            tex_file_writing.subprocess = original


def _tex_artifacts(output, label, mobject, template):
    from manimlib.utils.tex_file_writing import get_full_tex, get_tex_config

    _, preamble = get_tex_config(template)
    # This is precisely the labelled content requested by StringMobject; not a
    # separately interpreted reconstruction of the mathematical expression.
    content = mobject.get_content(is_labelled=mobject.use_labelled_svg)
    full_tex = get_full_tex(content, "\n".join([preamble, ""]))
    artifacts = {}
    for suffix, data in (("tex", full_tex), ("svg", mobject.get_svg_string())):
        path = output / (label + "." + suffix)
        path.write_text(data, encoding="utf-8")
        artifacts[suffix] = {"file": path.name, "sha256": _sha256(path)}
    return artifacts


@contextmanager
def create_source_pair(settings, output):
    """Yield source, target and metadata; matching stays in upstream Transform."""
    from manimlib import Text, Tex
    from manimlib.mobject.svg.text_mobject import register_font

    kind = settings.input_kind
    if kind == "text":
        from .exporter import DEFAULT_FONT

        use_system = settings.font_file is None or (
            Path(settings.font_file).resolve() == DEFAULT_FONT.resolve() and settings.font != "DejaVu Serif")
        font_file = resolve_system_font(settings.font) if use_system else Path(settings.font_file).resolve()
        coverage = validate_font_coverage(font_file, settings.source + settings.target, settings.font)
        actual_font = coverage["pango_family"]
        with register_font(font_file):
            import manimpango

            if actual_font not in manimpango.list_fonts():
                raise ValueError("Registered font family %r is not available to Pango; refusing fallback" % actual_font)
            source = Text(settings.source, font=actual_font, font_size=48).set_height(settings.glyph_height)
            target = Text(settings.target, font=actual_font, font_size=48).set_height(settings.glyph_height)
            yield source, target, {"kind": kind, "mobject_class": "manimlib.Text",
                                   "font": actual_font, "requested_font": settings.font,
                                   "actual_font": actual_font, "font_file": font_file.name if font_file else None,
                                   "font_sha256": _sha256(font_file) if font_file else None,
                                   "font_size": 48, "font_coverage": coverage,
                                   "font_resolution": "installed_system_font" if use_system else "explicit_font_file"}
    elif kind == "latex":
        if settings.tex_template != "basic":
            raise ValueError("Only the pinned ManimGL basic LaTeX template is currently supported")
        with native_tex_environment() as toolchain:
            source = Tex(settings.source, template=settings.tex_template).set_height(settings.glyph_height)
            target = Tex(settings.target, template=settings.tex_template).set_height(settings.glyph_height)
            artifacts = {label: _tex_artifacts(Path(output), label, mob, settings.tex_template)
                         for label, mob in (("source", source), ("target", target))}
            yield source, target, {"kind": kind, "mobject_class": "manimlib.Tex",
                                   "tex_template": settings.tex_template,
                                   "tex_environment": source.tex_environment,
                                   "toolchain": toolchain, "source_artifacts": artifacts}
    else:
        raise ValueError("input_kind must be text or latex")
