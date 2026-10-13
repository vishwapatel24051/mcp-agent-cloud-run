# Process Log: CSCI 599 Assignment 1

## 1. AI tools used

- Claude (Anthropic) in Claude Projects: planning the architecture, the first version of the code, tests, Dockerfile and README.
- Claude Code in VS Code (Claude Sonnet 5.5): running the project, debugging, testing the live service, and fixing problems.
- At runtime the agent itself uses NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b`.

## 2. Development narrative

I chose LangGraph with FastAPI because the assignment recommends it, NVIDIA NIM because it is free, and the filesystem and Tavily MCP servers plus fetch as a third. Later I added a fourth, small server of my own for exact arithmetic and time zones. USC accounts could not create Google Cloud projects, so I redeemed the $50 credit on a personal Gmail account, and once ran `gcloud config set project YOUR_PROJECT_ID` with the placeholder still in it.

The first real bug was launching the Node servers through `npx`: npm printed install messages on stdout and the MCP client reported "Failed to parse JSONRPC message". I switched to pinned versions and ran the binaries directly. The sample Dockerfile also copies packages into `/root/.local`, which the non-root user cannot read, so I used a venv in `/opt/venv`.

After deploying I tested with many prompts. NVIDIA's Lightning endpoint went DEGRADED, so I switched to Nemotron 3 Ultra. A burst of parallel requests after scale-to-zero failed and sessions lost memory, so I set `--min-instances 1`, raised memory and added retries. The agent emptied files when told to "delete everything", so I added a rule to ask first. Prompts that mattered: "can you test the project on different kinds of prompts also show me the prompts oyu are using and repsonses you got" (exposed the cold-start failures) and "fix it i dont want my project to break when grader is testing" (led to those fixes).

Running the image in Docker exposed that fetch was silently broken in the container: readabilipy runs `npm install` into site-packages, which the non-root user could not write, and Debian's Node 20 was too old for it. The model had been falling back to Tavily, which hid it. I fixed the Dockerfile and checked the live logs.

## 3. Verification narrative

- I had Claude write 10 offline tests with a scripted fake LLM driving the real graph against real MCP servers, then ran them (all pass): discovery on all four servers, a two-call chain, answering without tools, memory isolation between sessions, the calculator rejecting unsafe input, tool execution errors, and an unavailable server being skipped.
- For the three failure modes I had Claude Code write a tiny MCP server that crashes mid-call, writes garbage to the stream, returns a schema-violating result and returns `isError`. Running it showed that schema errors were mislabeled as connection failures, so I fixed the classification in `mcp_client.py`.
- I called each MCP tool by hand. A Tavily call with a fake key returned 403, which proved the request really reached the server.
- I had Claude Code run `scripts/smoke_test.sh` locally, in Docker and against the live Cloud Run URL, plus about 35 extra prompts: reasoning, code, multi-turn memory, chained tools, unicode, ambiguous input, missing files, a bad URL and invalid request bodies (HTTP 422).
- I had Claude Code read the Cloud Run logs to find out why some requests returned 500 (cold start, a second instance) and to confirm there were no `npm ERR` lines after the fetch fix, instead of trusting the model's answers.
- To test an unavailable server, I had Claude Code rename `node_modules/.bin/tavily-mcp` and restart the app. `/health` reported `tavily: unavailable` while the other servers stayed `ok`, and normal, file and fetch questions still worked. A web-search question was even answered through the fetch tool.

## 4. What I learned

The AI tools could write code that passed tests, but they couldn't tell me my deployment failed under a burst of requests or that fetch was silently broken inside the container; I only found those by testing the live service and reading the logs myself. I also had to work out that the LLM never touches files or the web itself, it only emits tool calls whose arguments match the JSON Schemas from `tools/list`. Keeping memory in RAM is why the service has to run on a single instance.
