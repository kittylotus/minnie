# Minnie

A local Disco Elysium research app for the supplied Jamais Vu FAYDE database. Python 3.12 or newer; no packages required.

## Run

```powershell
python app.py
```

Open http://localhost:8765. For a phone on the same Wi-Fi:

```powershell
python app.py --host 0.0.0.0
```

Open the phone address printed in the terminal and enter its access code. Allow Python through Windows Firewall on your private network if prompted. Keep the computer running. LAN access uses HTTP; use a trusted private network. This is a local app, not an Internet deployment or a phone-native offline app.

## Research

Dialogue search works immediately. Exact terms use SQLite FTS5; hybrid mode combines lexical rankings with semantic rankings using reciprocal rank fusion when embeddings exist. Semantic mode requires an index. Speaker and skill filters apply to retrieval. Alternate lines are included in lexical search and available in the evidence viewer. Citations use `conversation:line` because line IDs are only unique within conversations.

Settings accepts OpenAI-compatible `/v1` base URLs, model IDs and API keys for answers and embeddings separately. Keys are kept in `data/settings.json` on the host and never returned to the browser; protect this local file. A blank key preserves the saved key. Remove a key by editing that local file with the server stopped. Custom instructions control presentation; research rules require sourced claims and distinguish inference. Answer length is independent from Quick / Research / Exhaustive tool budgets (2 / 5 / 9 follow-up rounds).

Use **Load answer models** or **Load embedding models** to fetch that provider's `GET /v1/models` and select an ID. Enter a base URL ending in `/v1`; Minnie appends `/models`. You can fetch using unsaved URL/key fields without saving them, or use an existing saved key at the same endpoint. A changed URL requires re-entering its key for discovery. Each provider has its own list. Providers may list multiple model types; choose a model suitable for the corresponding API. Manual model entry remains available if listing is unsupported or empty.

Filter each loaded list with **Search answer models** or **Search embedding models**. Provider saves are independent; **Save custom instructions** only saves the instructions. **Ping** sends a small request to the selected text or embedding model and reports success and latency (and embedding dimensions). These checks use unsaved fields without saving them and may incur a small provider usage charge. The saved key is reused only at its saved endpoint.

**Ask the archive** streams provider responses over SSE, including progress across research tool rounds. Provider `reasoning_content`, `reasoning`, `reasoning_text`, text entries in `reasoning_details`, and `<think>`, `<thinking>`, `<reasoning>`, or `<analysis>` blocks are automatically separated into a collapsed **Model reasoning** panel. Partial tags spanning chunks are withheld until recognized. Only reasoning explicitly returned by the provider is displayed; hidden reasoning is not requested or recovered. Citations are verified after completion. Interrupted streams retain clearly labeled partial output, and providers that respond with ordinary JSON instead of SSE still display a completed answer.

Building the semantic index sends corpus text to your embedding provider and can cost money. Node representations include speaker, conversation title, alternates and actual linked branch context. Batches are persisted and resumable. Provider identity is recorded per vector; a different model uses its own index. The source hash invalidates generated data when the corpus changes. V1 has a node index enriched with graph context; a separate window-vector index is not yet implemented. Similarity scans run locally and can take longer on large indexes. Provider credentials are required for semantic indexing and answers; these calls cannot be validated without your provider.

The agent can search, expand graph context, inspect a conversation (up to 200 lines), find related passages and query the original database with SELECT/CTE SQL. SQL uses a read-only connection, an authorizer, a 3-second execution deadline, and a 200-row cap. Context expansion is capped and displays immediate branch links, conditions, checks, modifiers and alternatives. Citation IDs are checked against retrieved evidence; this does not guarantee the model's interpretation, so use the source viewer to verify claims.

Saved evidence, reading size, line spacing, and brightness live in this browser's local storage. They are not synchronized between desktop and phone. The subdued default palette is intentional and follows the supplied accessibility references.

## Research chats

Archive responses are now conversations. Ask a follow-up in the composer beneath the answer; earlier questions, answers and cited evidence inform the next research pass. **New chat** starts a separate thread. All completed turns, reasoning, citations and research traces are saved in `data/chats.sqlite` on the host, independently of the disposable corpus index. The chat library is shared by browsers and phones connected to that same host. Each browser remembers its last open chat locally.

Open **Chats** or **Organize chats** to create folders, move chats, rename chats or folders, pin/unpin either, and delete. Deleting a folder keeps its chats in Unfiled; deleting a chat permanently deletes its turns after confirmation. Pending turns prevent overlapping responses in a chat and are marked interrupted after a server restart. Failed questions remain saved and can be retried by sending another message. A disconnected stream is recorded as an interrupted turn; its partial output is not saved as a completed answer. Existing unsaved responses from before this feature cannot be recovered.

Full history remains saved and readable; model context currently includes up to the latest 12 completed turns within a 48,000-character question/answer budget, plus their cited sources. Reasoning is displayed but not fed back as chat context. Fresh searches supplement the previous evidence, and prior assistant prose is not treated as independent canon.

Answers render Markdown while reasoning remains plain text. Markdown supports headings, emphasis, lists, quotes, code blocks, links and tables. Marked 18.0.14 and DOMPurify 3.4.16 are vendored and served locally, with no CDN dependency. HTML is sanitized, remote images are suppressed, and citations become source buttons outside links and code blocks. Numeric-only records and structural HUB nodes are excluded from search and new embeddings; valid semantic-only results still appear with a null lexical score. Structural nodes remain available in graph context.

## Exploring dialogue branches

**Open dialogue context** follows outgoing database links in order, showing the spoken exchange until the next choice point. Select a dialogue choice to continue, or use **Previous branch** to go back. Structural HUB records are labeled as dialogue choice points instead of showing their placeholder `0`. Conditions, alternate lines, script effects, active checks and estimated passive skill requirements remain available. Minnie does not simulate your game state: conditional forks are shown as possible continuations, not silently chosen. Cycles and sequences longer than 100 linked nodes pause with an explicit continuation link.

## First semantic index

In **Settings → Embeddings**, enter your embedding provider's `/v1` base URL and API key, load models, and choose an embedding-capable model. Save that provider and use **Ping embedding provider** to verify it. Then select **Build semantic index** and keep Minnie running until it finishes. Interrupted builds resume when started again. Use the same provider URL and model for later searches. The app prepares its SQLite index automatically; no manual database conversion is needed. Building the index sends dialogue to the provider and may incur usage charges. Answer-model settings are separate.

## Data files

`source/` contains the extracted original DB and Ruby browser reference. The app opens the original database with `mode=ro`. `data/normalized.sqlite` contains the generated lexical index, metadata and vectors; `data/` is ignored by version control. The supplied source archives are retained.

## Verify

```powershell
python -m unittest discover -s tests -v
```
