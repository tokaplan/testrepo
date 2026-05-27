/**
 * Monkey-patches `globalThis.fetch` to log every POST to /chat/completions
 * or /responses, recording whether the request body contains `stream:true`.
 * Used to confirm the verifier sub-agent streams and the others don't.
 *
 * Run from the LangChain NodeJs project root:
 *   node --import ./probe_lcnode_stream.mjs main.js <runId>
 */

const origFetch = globalThis.fetch;
const callLog = [];

globalThis.fetch = async function patchedFetch(input, init) {
  try {
    const url = typeof input === "string" ? input : input?.url ?? "";
    const method = init?.method ?? (typeof input === "object" ? input?.method : "GET");
    if (
      method === "POST" &&
      (url.includes("/chat/completions") || url.includes("/responses"))
    ) {
      let body = init?.body ?? null;
      if (body && typeof body !== "string") {
        try {
          body = JSON.stringify(body);
        } catch {
          body = String(body);
        }
      }
      let stream = false;
      let model = "?";
      if (body) {
        try {
          const parsed = JSON.parse(body);
          stream = parsed?.stream === true;
          model = parsed?.model ?? "?";
        } catch {
          stream = /"stream"\s*:\s*true/.test(body);
        }
      }
      const tag = url.includes("/responses") ? "responses" : "chat.completions";
      console.log(
        `>>> [PROBE] POST ${tag} model=${model} stream=${stream}`
      );
      callLog.push({ tag, model, stream });
    }
  } catch (e) {
    console.log("[PROBE] error logging fetch:", e?.message);
  }
  return origFetch(input, init);
};

process.on("exit", () => {
  console.log("\n=== [PROBE] Summary ===");
  console.log(`Total LLM calls: ${callLog.length}`);
  const streamCount = callLog.filter((c) => c.stream).length;
  const nonStreamCount = callLog.length - streamCount;
  console.log(`  streaming:     ${streamCount}`);
  console.log(`  non-streaming: ${nonStreamCount}`);
  if (streamCount > 0 && nonStreamCount > 0) {
    console.log("  => MIXED MODE confirmed (at least one of each)");
  } else if (streamCount === 0) {
    console.log("  => All non-streaming");
  } else {
    console.log("  => All streaming");
  }
});
