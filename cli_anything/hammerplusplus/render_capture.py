"""On-demand native viewport readback in a disposable Windows worker.

Method profiles are tied to observed DLL bytes, rather than interface names
alone: Hammer's installed ReadPixels has an additional optional texture pointer.
The worker exits after capture so Frida's controller memory is not kept idle.
"""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from .backend import BackendError
from .project import Project, atomic_write

PROFILE = {
    "materialsystem.dll": "011e6fb57fa1856ae946a442a2aa2c930d5b15447b03c7e67a64337571f92cce",
    "shaderapidx9.dll": "18ba7e4ea0fb5a51e26b4517999911582ae91e7209267532882855f53cbf230a",
}

SCRIPT = r"""
function method(object,slot,type,args) {
  return new NativeFunction(object.readPointer().add(slot*4).readPointer(),type,['pointer',...args],'thiscall');
}
rpc.exports = {
  describe() {
    return {architecture:Process.arch,modules:['materialsystem.dll','shaderapidx9.dll'].map(name=>{
      const module=Process.getModuleByName(name);return {name,path:module.path};
    })};
  },
  arm() {
    const module=Process.getModuleByName('materialsystem.dll');
    const factory=new NativeFunction(module.getExportByName('CreateInterface'),'pointer',['pointer','pointer'],'mscdecl');
    const material=factory(Memory.allocUtf8String('VMaterialSystem080'),ptr(0));
    if(material.isNull())throw new Error('VMaterialSystem080 unavailable');
    const user=Process.getModuleByName('user32.dll');
    const getRect=new NativeFunction(user.getExportByName('GetClientRect'),'int',['pointer','pointer'],'stdcall');
    const getOwner=new NativeFunction(user.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer'],'stdcall');
    let view=ptr(0),done=false,reading=false,attempts=0,fallbackSent=false,buffer=null,capacity=0;
    Interceptor.attach(material.readPointer().add(41*4).readPointer(),{
      // x86 thiscall keeps this in ECX; args[0] is the first stack argument.
      onEnter(args){view=args[0];}
    });
    Interceptor.attach(material.readPointer().add(46*4).readPointer(),{
      onEnter(args){
        if(done||reading||attempts>=8||view.isNull())return;
        const rect=Memory.alloc(16);
        const owner=Memory.alloc(4);
        getOwner(view,owner);
        if(owner.readU32()!==Process.id)return;
        if(!getRect(view,rect))return;
        const viewWidth=rect.add(8).readS32()-rect.readS32();
        const viewHeight=rect.add(12).readS32()-rect.add(4).readS32();
        if(viewWidth<64||viewHeight<64)return;
        reading=true;attempts++;
        let context=ptr(0),pixels=null,error=null,width=0,height=0,backbufferWidth=0,backbufferHeight=0;
        try {
          context=method(material,115,'pointer',[])(material);
          if(context.isNull())throw new Error('Render context unavailable');
          const size=Memory.alloc(8);
          method(context,8,'void',['pointer','pointer'])(context,size,size.add(4));
          backbufferWidth=size.readS32();backbufferHeight=size.add(4).readS32();
          width=Math.min(backbufferWidth,viewWidth);height=Math.min(backbufferHeight,viewHeight);
          if(width<64||height<64||width>4096||height>4096||width*height>8388608)throw new Error('Viewport exceeds 8 megapixel capture limit');
          if(capacity<width*height*3){capacity=width*height*3;buffer=Memory.alloc(capacity);}
          // Binary-verified seven-argument ABI, including optional ITexture*.
          method(context,13,'void',['int','int','int','int','pointer','int','pointer'])(context,0,0,width,height,buffer,2,ptr(0));
          pixels=buffer.readByteArray(width*height*3);
        }catch(cause){error=String(cause);}
        finally{if(!context.isNull())method(context,1,'int',[])(context);reading=false;}
        if(error!==null){done=true;send({error});return;}
        // 2D helper views can swap a cleared buffer before the actual 3D pane.
        // Select a populated owned pane, bounded to eight native frame events.
        const data=new Uint8Array(pixels),colors=new Set();
        const right=Math.min(width,viewWidth),bottom=Math.min(height,viewHeight);
        for(let y=0;y<bottom&&colors.size<3;y+=Math.max(1,Math.floor(bottom/64))){
          for(let x=0;x<right&&colors.size<3;x+=Math.max(1,Math.floor(right/64))){
            const offset=(y*width+x)*3;
            colors.add((data[offset]<<16)|(data[offset+1]<<8)|data[offset+2]);
          }
        }
        const uniform=colors.size<3;
        if(!uniform||!fallbackSent){
          send({width,height,backbuffer_width:backbufferWidth,backbuffer_height:backbufferHeight,hwnd:view.toUInt32(),format:'RGB888',uniform,frames_examined:attempts},pixels);
          fallbackSent=true;
        }
        if(uniform)send({frame_progress:true,frames_examined:attempts,exhausted:attempts>=8});
        if(!uniform)done=true;
      }
    });
    return {armed:true};
  }
};
"""


def validate_profile(description):
    from .timeline import file_hash

    if description.get("architecture") != "ia32":
        raise BackendError("Viewport capture supports the verified x86 CS:GO runtime")
    modules = {row["name"].lower(): row["path"] for row in description["modules"]}
    for name, revision in PROFILE.items():
        if name not in modules or file_hash(Path(modules[name])) != revision:
            raise BackendError(
                "Native renderer DLL profile is unrecognized; unsafe interface calls were refused",
                {"module": name, "fallback": "Use method=window for native UI capture"},
            )
    return modules


def read_frame(pid, redraw):
    try:
        import frida
    except ImportError as exc:
        raise BackendError(
            "Native viewport capture requires the desktop extra (Frida)"
        ) from exc

    ready = threading.Event()
    frame = {}

    def message(value, binary):
        if ready.is_set():
            return
        if value["type"] == "error":
            frame["error"] = value.get(
                "stack", value.get("description", "Capture script failed")
            )
        elif value["type"] == "send":
            if value["payload"].get("frame_progress"):
                frame["frames_examined"] = value["payload"]["frames_examined"]
                if value["payload"].get("exhausted"):
                    ready.set()
                return
            frame.update(value["payload"])
            frame["pixels"] = binary
            if value["payload"].get("uniform"):
                return
        else:
            return
        ready.set()

    cancel = frida.Cancellable()
    timer = threading.Timer(12, cancel.cancel)
    timer.daemon = True
    session = script = None
    timer.start()
    try:
        with cancel:
            session = frida.attach(pid)
            script = session.create_script(SCRIPT)
            script.on("message", message)
            script.load()
            modules = validate_profile(script.exports_sync.describe())
            script.exports_sync.arm()
            redraw()
            if not ready.wait(8) and frame.get("pixels") is None:
                raise BackendError(
                    "No native viewport frame arrived within eight seconds"
                )
            if frame.get("error"):
                raise BackendError("Native viewport readback failed: " + frame["error"])
            width, height = frame["width"], frame["height"]
            if not (
                64 <= width <= 4096
                and 64 <= height <= 4096
                and width * height <= 8388608
            ):
                raise BackendError("Invalid native viewport dimensions")
            if (
                frame.get("pixels") is None
                or len(frame["pixels"]) != width * height * 3
            ):
                raise BackendError("Native viewport returned an incomplete RGB frame")
            # An empty/off-map camera can legitimately produce a uniform frame.
            # Preserve the actual pixels and report this, rather than fabricating
            # geometry or substituting a UI screenshot as rendered content.
            step = max(1, width * height // 8192) * 3
            colors = {
                frame["pixels"][offset : offset + 3]
                for offset in range(0, len(frame["pixels"]), step)
            }
            varied = len(colors) >= 3
            return {
                **frame,
                "modules": modules,
                "uniform": not varied,
                "content_has_variation": varied,
            }
    finally:
        timer.cancel()
        if session is not None:
            # A fresh bounded cancellation scope allows cleanup after a timeout.
            cleanup = frida.Cancellable()
            cleanup_timer = threading.Timer(3, cleanup.cancel)
            cleanup_timer.daemon = True
            cleanup_timer.start()
            try:
                with cleanup:
                    session.detach()
            finally:
                cleanup_timer.cancel()


def capture(project, config, pid, output, session_id):
    from . import desktop

    desktop._assert_owned(project, config, pid)
    path = project.confined(output)
    if path.suffix.lower() != ".png" or path.exists():
        raise BackendError("Capture output must be a new PNG inside the workspace")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                __name__,
                "--worker",
                str(project.root),
                session_id,
                output,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            "Native viewport capture worker exceeded twenty seconds"
        ) from exc
    try:
        receipt = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            "Native viewport worker returned no receipt",
            {"stderr": result.stderr[-4000:]},
        ) from exc
    if result.returncode or not receipt["ok"]:
        raise BackendError(
            receipt.get("error", "Native viewport worker failed"),
            receipt.get("details"),
        )
    return {**receipt["data"], "capture_worker_exited": True}


def worker(project, session_id, output):
    from . import desktop, native_session
    from PIL import Image

    api, con, _, gui, _, process, service = native_session._win32()
    directory = native_session._directory(project, session_id)
    launch = json.loads((directory / "launch.json").read_text("utf-8"))
    state = json.loads((directory / "session.json").read_text("utf-8"))
    config = {**launch["config"], "hammer": launch["configured_editor"]}
    pid = state["editor"]["pid"]
    native_session.find_session(project, config, pid)
    owned = service.OpenDesktop(state["desktop"], 0, False, con.GENERIC_ALL)
    owned.SetThreadDesktop()
    # Retain the process object so its PID cannot be reused during attachment.
    target_handle = api.OpenProcess(con.SYNCHRONIZE, False, pid)
    try:
        native_session._verify_identity(state["editor"])
        desktop._owned_pid = pid
        from .windows import set_dpi_awareness

        set_dpi_awareness()

        def redraw():
            for handle in desktop.owned_windows(pid):
                if gui.GetClassName(handle) == "HammmerPlusPlus":
                    # Force paint on owned children. The worker's outer deadline
                    # bounds a hung target, without focus or global input.
                    gui.RedrawWindow(handle, None, None, 0x185)

        frame = read_frame(pid, redraw)
        path = project.confined(output)
        if path.suffix.lower() != ".png" or path.exists():
            raise BackendError("Capture output must be a new PNG inside the workspace")
        image = Image.frombytes(
            "RGB", (frame["width"], frame["height"]), frame.pop("pixels")
        )
        try:
            with BytesIO() as encoded:
                image.save(encoded, format="PNG")
                atomic_write(path, encoded.getvalue(), exclusive=True)
        finally:
            image.close()
        return {
            "path": str(path),
            "pid": pid,
            **frame,
            "method": "native-viewport",
            "capture_worker_pid": os.getpid(),
            "capture_worker_peak_working_set_bytes": process.GetProcessMemoryInfo(
                api.GetCurrentProcess()
            )["PeakWorkingSetSize"],
            "verification": "Actual Hammer++ render-thread RGB readback; inspect the image before making geometry or gameplay claims",
            "limitations": "One native viewport; use method=window for UI chrome",
            "warnings": (
                []
                if frame["content_has_variation"]
                else [
                    "Uniform viewport pixels; inspect camera position and map contents before claiming visible geometry"
                ]
            ),
        }
    finally:
        target_handle.Close()
        # The disposable worker exits immediately; Windows releases its thread
        # desktop handles and instrumentation helpers before the caller returns.


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--worker":
        raise SystemExit("Viewport worker is launched by capture_editor")
    try:
        value = {
            "ok": True,
            "data": worker(Project(sys.argv[2]), sys.argv[3], sys.argv[4]),
        }
    except Exception as exc:
        value = {"ok": False, "error": str(exc), "details": getattr(exc, "details", {})}
    print(json.dumps(value, ensure_ascii=True))
    raise SystemExit(0 if value["ok"] else 1)
