# Native material and stencil compatibility research

This finite probe compares ordinary native rendering against the unchanged
integrated stencil carrier from commit `0c8800c`. It separates a resource-pack
override that affects rendering while the carrier is hidden from interference
that appears only when the carrier writes its stencil bits. It is research
tooling, with no alpha packing, capacity expansion, or continuous updates.

The stock package uses the installed client's exact `sfx.material` and omits
the experimental terrain material. The carrier package retains the frozen
integrated materials and shaders. Both packages receive identical ordinary
FrameAni and native inventory-item renderer fixtures. Their manifest identities
are distinct, and the owner runs them sequentially.

The first native matrix used client `3.10.0.467018`, a 720×1080 viewport, source
ROI `[8,128,512,512]`, an actual 65,536-byte host input, and diagnostic output at
Y650. The stock baseline does not build the carrier's block geometry. The
carrier retains one clear page and two writer pages, with at least 4 GiB
available system commit required before each native build and `load_begin`.

## Native results established before any material fix

Evidence is preserved under the repository's ignored directory
`.runtime/native-stencil-compat-20261119-r1/`.

- Ordinary FrameAni: all four tested `no_depth_test` material routes pass their
  stock RGB/texture positive controls inside and outside the source ROI. In the
  unchanged carrier package, all four disappear both with carrier data hidden
  and with it active. The stock and carrier off-background patches match
  exactly. Complete carrier identity and raw-source diagnostics remain exact.
  This establishes a global material override conflict. It does not test every
  declared material permutation, depth-write mode, or cylinder effect.
- Native inventory-item renderer: normal, enchanted, and empty widgets pass
  temporal glint and stable-control checks with the carrier off and active,
  including exhaustive data screenshots. This fixture is a custom JSON UI that
  uses the unmodified native renderer. The separate lifecycle helper also opens
  the actual stock inventory screen.
- Natural entity shadow: a stationary cube hovering above a restored stone
  floor has 377 source-inside and 382 source-outside native shadow pixels. With
  the carrier active, exactly 196 source-inside shadow pixels change; every
  changed position has source stencil bit64 set, and every bit64-clear shadow
  position stays within the restoration tolerance. The source-outside shadow
  is unchanged. The same screenshots retain exact full input/source outputs.
  The first failed geometry mask and its corrected predeclared hover fixture
  are both preserved.
- Native inventory/pause return, carrier visibility changes, moving the ROI,
  and resizing the viewport retain the same allocations and exact reads.
- A real Overworld → Nether → Overworld trip loses the client-only geometry;
  settled screenshots without rebinding show the expected all-zero carrier
  output rather than the original bytes. The original return attempt during
  loading and the bounded public-API recovery are both preserved.
- Both actual resource-pack list relations were verified with a separate pack
  containing the installed native SFX bytes and an independent UI canary. The
  extra pack appears before the carrier in one deployed world list and after
  it in the other. In both cases all 42 captured canaries are exact, all eight
  ordinary FrameAni cases remain absent, and all 16 exhaustive diagnostics
  remain exact. This observes carrier behavior in both tested relations; it
  does not identify the engine's material resolver or establish that list
  position controls material precedence. The first failed passive loader and
  its fresh v1.0.1 recovery packs are preserved separately.
- Native target-face highlighting passes with the data carrier. A normal
  attached first-person pick hits the frozen near face; 190,720 filled-face
  pixels change, including 156,460 source-inside and 34,260 source-outside
  pixels. Corresponding native/carrier regions remain within two RGB levels,
  including the same screenshots that contain complete identity/source data
  and all guards. F1-equivalent global HUD hiding suppressed the original
  positive control. A HUD-visible retry exposed bottom-slotbar guard
  occlusion; the final retry hides individual HUD parts while preserving the
  native world effect and retains the unchanged Y650 pixel gates. All three
  attempts and exact block/player/camera restoration are retained.
- Actual 1× and 4× MSAA startup cases are distinguished by an isolated shader
  macro witness outside the data ROI, and exhaustive reads pass in each.
- Original native DOF has a confirmed raw-T1 bypass under a zero-blur profile:
  active final RGB exactly matches the encoded fixture at all 262,144 source
  pixels while the earlier restored-RGB reference and exhaustive late reads
  pass. A nonzero native blur changes 262,142 pixels, then returns to exact
  original RGB at zero scales. Original Bloom remains unproven because its
  bounded native visual controls show no response; passing reads and an
  enabled flag alone are not Bloom execution evidence.

Independent audits and exact native captures remain the acceptance evidence;
derived comparison images are for review. These observations do not establish
compatibility on other native render routes, clients, devices, or platforms.

## Owner and interfaces

Only the lifecycle owner uses the game. Other helpers build assets or verify
existing evidence. All calls use the explicit owner
`manim-native-stencil-compat`, its assigned session, a 60 FPS cap, protected
noactivation, and fresh passive Windows Graphics Capture. User foreground
permission never authorizes agent activation or desktop input.

`build_probe.build(output, game_exe, variant, include_enchanted=False)` composes
the frozen integrated builder and independent fixtures. `variant` is initially
`stock` or `carrier`; it does not silently install a compatibility fix.

`runner.Experiment` provides:

- `initialize()` for the ordinary isolated-native-post configuration.
- `call(label, code, expression)` and `server(label, code)` for owner-bound
  public ModSDK calls. Server code must set `_result=json.dumps(...)`.
- `raw_capture(label, configuration='off')` for a passive native scene image.
- `data_checks(prefix)` for full identity mode1 and raw-source mode3, with
  complete output guards at Y650.
- The inherited integrated `capture`, `memory`, and host-byte loading methods.

The runtime system remains `pmanim_stencil_integrated / probe`. Host helpers
import the existing integrated implementation without changing its packaged
runtime, material, or shader files. Game Python writes no files; builds and
evidence are host-side operations.

`frameani_runner.py` initializes one fresh instance and runs finite ordinary
effect comparisons. `continue_runner.py` hydrates a fresh evidence directory
on the same already-owned instance for glint, shadow, target selection,
lifecycle, and final dimension cases. Keep dimension changes last because the
client-only entities can be invalidated.

`pack_order_runner.py` checks actual deployed resource UUID order and a unique
native UI canary, then captures ordinary effects and complete payload outputs.
It preserves negative pixel results without ending unrelated cases. An input
list position is not itself a priority claim. Both actual deployed relations
and conflicting native material outcomes must be inspected. It preserves an
exact assigned-session snapshot before the run, together with the host,
FrameAni runner, and canary verifier hashes. The extra behavior pack's passive
client loader must be present; its Python class existing on disk alone does
not establish that the engine can import it.

Camera setup separates the public detach request from anchor creation. It
waits for finite position and nonzero forward vectors on a later render turn,
then builds the anchor from those accepted literals. A partial existing setup
is rejected. This addresses a fresh-start case in which the camera's forward
getter temporarily returns `None` after detachment without changing the frozen
game runtime.

Native bloom/DOF startup fixtures have a separate initializer in
`../native_stencil_post_fixture/`; ordinary `initialize()` intentionally rejects
startup-enabled native effects. The MSAA helper uses an isolated shader witness
outside the data ROI and changes native options only while zero games are
active. Configuration values alone do not prove a different active AA path.

`cleanup.py` disables owned fixtures where still valid, requests normal stop,
preserves a failed normal stop, and then uses the authorized owner-bound force
fallback. It verifies owned PID absence and zero active Minecraft processes.
Inactive historical CIM objects are not terminated. `serial_matrix.py` runs
explicitly selected fresh cases sequentially and will not continue after
unverified cleanup. It must not run while another owner has the native slot.
