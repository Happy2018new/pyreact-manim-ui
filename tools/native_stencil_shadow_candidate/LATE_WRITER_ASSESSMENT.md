# Public transparency controls do not establish late-writer scheduling

This is a static assessment only. No runtime calls, new native captures or
writer/shadow production changes were made.

The frozen carrier routes clear to `opaque`, bit64 to `alpha`, and bit128 to
`blend` in `tools/weather_stencil_large_probe/build_probe.py`. Installed client
`3.10.0.467018` declares
`netease_block_as_mesh_blend_enable_transparency:netease_block_as_mesh_blend`
as an empty child of blend. The blend base adds `BLEND`/`Blending`, but the
frozen builder overrides both aliases with the same writer128 definition.
Configured categories and material names do not establish an actual pass order
relative to native shadow rendering.

The public `EnableActorBlockGeometryTransparent` interface permits transparency;
`SetActorBlockGeometryTransparency` adjusts its amount in `[0,1]`. Their
documentation provides no render-queue order, native shadow timing, selected
material getter or scheduling guarantee. Installed
`data/shaders/glsl/netease_block_as_entity.fragment` multiplies alpha by the
separately named scalar `COMMON_BLOCK_GEO_FLOAT1_1`. The frozen clear/scatter
shaders do not read that scalar. All four existing `EXTRA_ACTOR_UNIFORM` vectors
are assigned to layout, ROI, calibration, enable state and byte offset. The
static sources do not prove a collision between the separate scalar and those
vectors, or an effect of the opacity value on custom stencil writes.

The prior `rain_geometry_probe` tried native transparency permission and
amounts 1.0/0.5 on resident geometry. Its known-color control did not expose
writer blend, and it did not establish two different render queues.

A narrow future experiment could keep the installed native shadow material
unchanged and request transparency **off → enabled with amount1 → off** on the
same resident page. First, an isolated ROI-outside marker for each proposed
material alias would have to establish two different shader routes. Every state
would then retain actual source-symbol checks, full identity/raw data, every
guard and native shadow off/on/off controls. The initial conclusion would be
about an observed public-setting/render-result relationship. Without a separate
timing witness, it would still not prove that either writer executes after the
native shadow stage.

The three-mask experiment prepared here therefore keeps writer routing frozen.
It directly checks whether excluding overlay read bits preserves native shadow
pixels in each actual `00/01/10/11` payload class while retaining complete data.
Existing per-page visibility, shadow toggles and same-PNG diagnostics can decide
which data bits correlate with visual interference and whether bytes survive.
They cannot uniquely attribute that result to alpha/blend scheduling.
