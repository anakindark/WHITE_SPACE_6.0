import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import {
  Client,
  StreamableHTTPClientTransport,
} from "@modelcontextprotocol/client";

import { startBridge } from "../server.js";

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(server.address().port);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    server.close(() => resolve());
  });
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString("utf8");
  return text ? JSON.parse(text) : {};
}

test("bridge is live-state driven, fail-closed, and cannot execute", async () => {
  const observedProposals = [];
  let failState = false;

  const mockApi = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");

    const send = (status, value) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(value));
    };

    if (req.method === "GET" && url.pathname === "/health") {
      send(200, { status: "PASS", runtime: "TEST" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/state") {
      if (failState) {
        send(503, { error: "state unavailable" });
        return;
      }
      send(200, { head: "RTEST", queue: 0, authority: "PASS" });
      return;
    }
    if (req.method === "GET" && url.pathname === "/queue") {
      send(200, { depth: 0 });
      return;
    }
    if (req.method === "GET" && url.pathname === "/capabilities") {
      send(200, { capabilities: ["READ", "PROPOSE_ONLY"] });
      return;
    }
    if (req.method === "POST" && url.pathname === "/proposals") {
      const body = await readJson(req);
      observedProposals.push(body);
      send(202, { accepted: true, pending_human_approval: true });
      return;
    }

    send(404, { error: "not found" });
  });

  const mockPort = await listen(mockApi);
  const bridge = await startBridge({
    env: {
      ...process.env,
      HOST: "127.0.0.1",
      PORT: "0",
      MCP_PATH: "/mcp",
      WS_API_BASE: `http://127.0.0.1:${mockPort}`,
      WS_ALLOWED_API_HOSTS: "127.0.0.1",
      WS_ENABLE_PROPOSALS: "true",
      WS_TIMEOUT_MS: "2000",
      WS_MAX_RESPONSE_BYTES: "65536",
    },
    logger: { error() {} },
  });

  const client = new Client(
    { name: "white-space-bridge-test", version: "1.0.0" },
    { versionNegotiation: { mode: "auto" } }
  );
  const transport = new StreamableHTTPClientTransport(
    new URL(`http://127.0.0.1:${bridge.port}/mcp`)
  );

  try {
    await client.connect(transport);

    const { tools } = await client.listTools();
    const names = tools.map((tool) => tool.name);

    assert.ok(names.includes("bridge_contract"));
    assert.ok(names.includes("runtime_health"));
    assert.ok(names.includes("system_state"));
    assert.ok(names.includes("queue_status"));
    assert.ok(names.includes("capabilities"));
    assert.ok(names.includes("propose_action"));
    assert.ok(!names.includes("approve_action"));
    assert.ok(!names.includes("execute_action"));

    const state = await client.callTool({ name: "system_state" });
    assert.notEqual(state.isError, true);
    assert.equal(state.structuredContent.data.head, "RTEST");
    assert.match(state.structuredContent.state_sha256, /^[a-f0-9]{64}$/);

    const proposal = await client.callTool({
      name: "propose_action",
      arguments: {
        action: "diagnose_queue",
        reason: "integration test",
        parameters: { scope: "safe" },
      },
    });
    assert.notEqual(proposal.isError, true);
    assert.equal(observedProposals.length, 1);
    assert.equal(observedProposals[0].requires_human_approval, true);
    assert.equal(observedProposals[0].approved, false);
    assert.equal(observedProposals[0].execute, false);
    assert.match(
      observedProposals[0].observed_state_sha256,
      /^[a-f0-9]{64}$/
    );

    failState = true;
    const failedRead = await client.callTool({ name: "system_state" });
    assert.equal(failedRead.isError, true);
  } finally {
    await client.close().catch(() => {});
    await bridge.close();
    await closeServer(mockApi);
  }
});

test("proposal tool is absent by default", async () => {
  const mockApi = createServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "PASS" }));
  });

  const mockPort = await listen(mockApi);
  const bridge = await startBridge({
    env: {
      ...process.env,
      HOST: "127.0.0.1",
      PORT: "0",
      WS_API_BASE: `http://127.0.0.1:${mockPort}`,
      WS_ALLOWED_API_HOSTS: "127.0.0.1",
      WS_ENABLE_PROPOSALS: "false",
    },
    logger: { error() {} },
  });

  const client = new Client(
    { name: "white-space-readonly-test", version: "1.0.0" },
    { versionNegotiation: { mode: "auto" } }
  );

  try {
    await client.connect(
      new StreamableHTTPClientTransport(
        new URL(`http://127.0.0.1:${bridge.port}/mcp`)
      )
    );
    const { tools } = await client.listTools();
    assert.ok(!tools.some((tool) => tool.name === "propose_action"));
  } finally {
    await client.close().catch(() => {});
    await bridge.close();
    await closeServer(mockApi);
  }
});
