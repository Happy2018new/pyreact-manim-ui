# Static dimension recovery candidate

This separate candidate composes into a newly generated `carrier` native compatibility project. Frozen probe files and materials stay byte-for-byte unchanged. Installation adds a subclass and changes only the generated system registration and project receipt.

```powershell
python -B tools/native_stencil_dimension_candidate/build_candidate.py --project <fresh-carrier-project>
```

The serial matrix owns launch and cleanup through the original `native_stencil_compat_probe/host.py` and `cleanup.py`. After launch, invoke:

```powershell
python -B tools/native_stencil_dimension_candidate/runner.py --project <fresh-carrier-project> --evidence <new-run-directory> --previous-evidence <launch-evidence-directory> --repeats 2
```

The runner initializes the original 64 KiB carrier. It requires a controlled fresh Overworld and the original 720×1080 viewport. It makes one to three Nether round trips and restores the original fixed camera pose in each dimension. End is omitted because this harness does not establish an equivalent controlled End pose.

At local-player dimension start the candidate invalidates ready state and cached post links. A matching finish event and a later render turn permit camera setup. Later turns recreate client actors and late FrameAni readers, attach the same retained native geometry names, and reconnect all three texture links. The original bytes, checksum, host identity, generation, native page names and native Combine attempt count must stay unchanged. Optional scene fixtures must be disabled. No game file writes or continuous updates are added.

ModSDK documents that dimension changes automatically clear client-only entities. Native geometry cache survival is a hypothesis for this candidate. An accepted attachment is recorded as an API response, never as proof of rendered data. A rejected attachment, partial post-process loss, invalid event ordering, changed identity or timeout faults recovery. There is no automatic Combine retry or fallback to another data route.

After each automatic recovery the runner first takes a passive capture without changing probe controls, and applies the frozen exact byte/guard verifier. It then applies the original mode 1 and mode 3 exact checks. Both outgoing and returning dimensions must pass; failure returns a nonzero process code. A return is attempted from `finally`, and its failure remains separate from the outgoing failure. The generated `dimension-candidate-status.json` is the case result. `pixel_verified` is only true after every requested trip passes all readbacks. Runtime state always leaves `pixel_verified` false because runtime API responses cannot verify pixels.

Offline tests do not launch Minecraft:

```powershell
python -B -m unittest discover -s tools/native_stencil_dimension_candidate -p "test_*.py"
```

The candidate keeps original launch evidence and the frozen sources unchanged. It retains the owned game for the serial matrix's existing cleanup. No real-device verification is claimed by installation or offline tests.
