import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";

const PORT = Number(process.env.PORT ?? 8787);
const HOST = process.env.HOST ?? "127.0.0.1";
const MCP_PATH = process.env.MCP_PATH ?? "/mcp";

const WS_API_BASE = process.env.WS_API_BASE ?? "http://127.0.0.1:8820";
const WS_HEALTH_PATH = process.env.WS_HEALTH_PATH ?? "/health";
const WS_STATE_PATH = process.env.WS_STATE_PATH ?? "/state";
const WS_QUEUE_PATH = process.env.WS_QUEUE_PATH ?? "/queue";
const WS_CAPABILITIES_PATH = process.env.WS_CAPABILITIES_PATH ?? "/capabilities";
const WS_PROPOSAL_PATH = process.env.WS_PROPOSAL_PATH ?? "/proposals";
const WS_TIMEOUT_MS = Number(process.env.WS_TIMEOUT_MS ?? 5000);
const WS_BRIDGE_BEARER_TOKEN = process.env.WS_BRIDGE_BEARER_TOKEN ?? "";

function ensureSafeBaseUrl(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("WS_API_BASE must use http or https.");
  }
  return url;
}

const wsBaseUrl = ensureSafeBaseUrl(WS_API_BASE);

function endpoint(path) {
  if (!path.startsWith("/")) {
    throw new Error("WHITE_SPACE API paths must start with '/'.");
  }
  return new URL(path, wsBaseUrl).toString();
}

async function wsRequest(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), WS_TIMEOUT_MS);

  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (WS_BRIDGE_BEARER_TOKEN) {
    headers.authorization = `Bearer ${WS_BRIDGE_BEARER_TOKEN}`;
  }

  try {
    const response = await fetch(endpoint(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });

    const raw = await response.text();
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = { raw };
    }

    if (!response.ok) {
      throw new Error(
        `WHITE_SPACE API returned ${response.status}: ${JSON.stringify(data)}`
      );
    }

    return data;
  } finally {
    clearTimeout(timer);
  }
}

function sha256(value) {
  return createHash("sha256")
    .update(JSON.stringify(value))
    .digest("hex");
}

function result(message, data) {
  return {
    content: [{ type: "text", text: message }],
    structuredContent: data,
  };
}

function createWhiteSpaceServer() {
  const server = new McpServer(
    {
      name: "white-space-controller",
      version: "0.1.0",
    },
    {
      instructions:
        "WHITE_SPACE is canonical; chat context is not. Read live state before any proposal. " +
        "This bridge exposes observation plus proposal creation only. It never approves or executes a proposal. " +
        "Human approval remains authoritative.",
    }
  );

  server.registerTool(
    "bridge_contract",
    {
      title: "Read WHITE_SPACE bridge contract",
      description:
        "Returns the fixed authority model for this bridge. Use this to confirm who owns state, execution, tool contracts, and final approval.",
      inputSchema: {},
      outputSchema: {
        chat: z.literal("non-canonical controller"),
        white_space_api: z.literal("source of truth"),
        pc_runtime: z.literal("canonical executor"),
        mcp_tools: z.literal("contract"),
        human_final: z.literal("authority"),
        execution_available: z.literal(false),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async () =>
      result("WHITE_SPACE authority contract loaded.", {
        chat: "non-canonical controller",
        white_space_api: "source of truth",
        pc_runtime: "canonical executor",
        mcp_tools: "contract",
        human_final: "authority",
        execution_available: false,
      })
  );

  server.registerTool(
    "runtime_health",
    {
      title: "Read WHITE_SPACE runtime health",
      description:
        "Reads the live runtime health from WHITE_SPACE. Do not infer health from chat history.",
      inputSchema: {},
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(WS_HEALTH_PATH);
      return result("Live WHITE_SPACE runtime health read.", { data });
    }
  );

  server.registerTool(
    "system_state",
    {
      title: "Read canonical WHITE_SPACE state",
      description:
        "Reads the current canonical WHITE_SPACE state directly from the API. Use before interpreting or proposing changes.",
      inputSchema: {},
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(WS_STATE_PATH);
      return result("Canonical WHITE_SPACE state read.", {
        data,
        state_sha256: sha256(data),
      });
    }
  );

  server.registerTool(
    "queue_status",
    {
      title: "Read WHITE_SPACE queue status",
      description:
        "Reads the live WHITE_SPACE queue without changing it.",
      inputSchema: {},
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(WS_QUEUE_PATH);
      return result("Live WHITE_SPACE queue status read.", { data });
    }
  );

  server.registerTool(
    "capabilities",
    {
      title: "Read WHITE_SPACE capabilities",
      description:
        "Reads the current capability surface exposed by WHITE_SPACE. The returned data is authoritative only for the moment it was read.",
      inputSchema: {},
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(WS_CAPABILITIES_PATH);
      return result("Live WHITE_SPACE capabilities read.", { data });
    }
  );

  server.registerTool(
    "propose_action",
    {
      title: "Create a WHITE_SPACE action proposal",
      description:
        "Creates a proposal for the local WHITE_SPACE runtime. This does not approve or execute anything. Human approval is required outside this MCP bridge.",
      inputSchema: {
        action: z.string().min(1).max(120),
        reason: z.string().min(1).max(2000),
        parameters: z.record(z.unknown()).optional(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        openWorldHint: false,
      },
    },
    async ({ action, reason, parameters = {} }) => {
      const currentState = await wsRequest(WS_STATE_PATH);
      const observedStateSha256 = sha256(currentState);
      const proposalId = randomUUID();

      const proposal = {
        proposal_id: proposalId,
        action,
        reason,
        parameters,
        requested_by: "chatgpt-mcp",
        requires_human_approval: true,
        approved: false,
        execute: false,
        observed_state_sha256: observedStateSha256,
      };

      const response = await wsRequest(WS_PROPOSAL_PATH, {
        method: "POST",
        body: proposal,
      });

      return result(
        "Proposal created. No action was approved or executed by this bridge.",
        {
          proposal_id: proposalId,
          observed_state_sha256: observedStateSha256,
          requires_human_approval: true,
          executed: false,
          runtime_response: response,
        }
      );
    }
  );

  return server;
}

const httpServer = createServer(async (req, res) => {
  if (!req.url) {
    res.writeHead(400).end("Missing URL");
    return;
  }

  const url = new URL(req.url, `http://${req.headers.host ?? "localhost"}`);

  if (req.method === "GET" && url.pathname === "/") {
    res
      .writeHead(200, { "content-type": "application/json" })
      .end(
        JSON.stringify({
          service: "WHITE_SPACE MCP bridge",
          mode: "non-canonical-controller",
          mcp: MCP_PATH,
          execution_available: false,
        })
      );
    return;
  }

  if (req.method === "OPTIONS" && url.pathname === MCP_PATH) {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "content-type, mcp-session-id",
      "Access-Control-Expose-Headers": "Mcp-Session-Id",
    });
    res.end();
    return;
  }

  const allowedMethods = new Set(["POST", "GET", "DELETE"]);
  if (url.pathname === MCP_PATH && req.method && allowedMethods.has(req.method)) {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");

    const server = createWhiteSpaceServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });

    res.on("close", () => {
      transport.close();
      server.close();
    });

    try {
      await server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (error) {
      console.error("MCP request failed:", error);
      if (!res.headersSent) {
        res.writeHead(500).end("Internal server error");
      }
    }
    return;
  }

  res.writeHead(404).end("Not Found");
});

httpServer.listen(PORT, HOST, () => {
  console.log(
    `WHITE_SPACE MCP bridge listening on http://${HOST}:${PORT}${MCP_PATH}`
  );
  console.log(`WHITE_SPACE API base: ${wsBaseUrl.toString()}`);
  console.log("Execution tools are intentionally disabled; human approval remains final.");
});
