import {
  Client,
  StreamableHTTPClientTransport,
} from "@modelcontextprotocol/client";

const mcpUrl = process.env.MCP_URL ?? "http://127.0.0.1:8787/mcp";
const requiredTools = [
  "bridge_contract",
  "runtime_health",
  "system_state",
  "queue_status",
  "capabilities",
];

function cleanResult(result) {
  return {
    isError: result?.isError === true,
    structuredContent: result?.structuredContent ?? null,
    content: Array.isArray(result?.content)
      ? result.content
          .filter((item) => item?.type === "text")
          .map((item) => String(item.text ?? "").slice(0, 2000))
      : [],
  };
}

const client = new Client(
  { name: "white-space-live-verifier", version: "1.0.0" },
  { versionNegotiation: { mode: "auto" } }
);

try {
  await client.connect(new StreamableHTTPClientTransport(new URL(mcpUrl)));
  const listed = await client.listTools();
  const names = listed.tools.map((tool) => tool.name).sort();
  const missing = requiredTools.filter((name) => !names.includes(name));
  if (missing.length > 0) {
    throw new Error(`missing required MCP tools: ${missing.join(", ")}`);
  }

  const calls = {};
  for (const name of requiredTools) {
    const result = await client.callTool({ name });
    calls[name] = cleanResult(result);
    if (result?.isError === true) {
      throw new Error(`MCP tool returned error: ${name}`);
    }
  }

  const stateHash =
    calls.system_state?.structuredContent?.state_sha256 ?? null;
  if (typeof stateHash !== "string" || !/^[a-f0-9]{64}$/.test(stateHash)) {
    throw new Error("system_state did not return a valid SHA-256 state hash");
  }

  process.stdout.write(
    `${JSON.stringify(
      {
        status: "PASS",
        mcp_url: mcpUrl,
        tools: names,
        state_sha256: stateHash,
        calls,
      },
      null,
      2
    )}\n`
  );
} catch (error) {
  process.stderr.write(
    `${JSON.stringify(
      {
        status: "FAIL",
        mcp_url: mcpUrl,
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2
    )}\n`
  );
  process.exitCode = 1;
} finally {
  await client.close().catch(() => {});
}
