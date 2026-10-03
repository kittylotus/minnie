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

In **Settings → Phone access**, choose and confirm your own access password (6–128 characters), then select **Change access password**. The password is saved as a salted PBKDF2 hash in ignored `data/access.json`; the initial generated code is replaced. The saved password and device sessions survive Minnie restarts. Successful login sets a persistent, HttpOnly cookie for 180 days, subject to the browser's cookie policies. Changing the password rotates the session token, signs other devices out, and keeps the device making the change connected. You can always change it from localhost on the computer running Minnie. Keep using the same phone browser/profile and hostname; clearing cookies requires signing in again. Existing installations need one new login after updating from the old code-per-restart behavior.

## Research

Dialogue search works immediately. Exact terms use SQLite FTS5; hybrid mode combines lexical rankings with semantic rankings using reciprocal rank fusion when embeddings exist. Semantic mode requires an index. Speaker and skill filters apply to retrieval. Alternate lines are included in lexical search and available in the evidence viewer. Citations use `conversation:line` because line IDs are only unique within conversations.

Settings accepts OpenAI-compatible `/v1` base URLs, model IDs and API keys for answers and embeddings separately. Keys are kept in `data/settings.json` on the host and never returned to the browser; protect this local file. A blank key preserves the saved key. Remove a key by editing that local file with the server stopped. Prompt presets control the main instructions, persona, and formatting. The default research preset requires sourced claims and distinguishes inference. Answer length is independent from Quick / Research / Exhaustive tool budgets (2 / 5 / 9 follow-up rounds).

Use **Load answer models** or **Load embedding models** to fetch that provider's `GET /v1/models` and select an ID. Enter a base URL ending in `/v1`; Minnie appends `/models`. You can fetch using unsaved URL/key fields without saving them, or use an existing saved key at the same endpoint. A changed URL requires re-entering its key for discovery. Each provider has its own list. Providers may list multiple model types; choose a model suitable for the corresponding API. Manual model entry remains available if listing is unsupported or empty.

Filter each loaded list with **Search answer models** or **Search embedding models**. Provider saves are independent; prompt presets have their own Save action. **Ping** sends a small request to the selected text or embedding model and reports success and latency (and embedding dimensions). These checks use unsaved fields without saving them and may incur a small provider usage charge. The saved key is reused only at its saved endpoint.

**Ask the archive** streams provider responses over SSE, including progress across research tool rounds. Provider `reasoning_content`, `reasoning`, `reasoning_text`, text entries in `reasoning_details`, and `<think>`, `<thinking>`, `<reasoning>`, or `<analysis>` blocks are automatically separated into a collapsed **Model reasoning** panel. Partial tags spanning chunks are withheld until recognized. Only reasoning explicitly returned by the provider is displayed; hidden reasoning is not requested or recovered. Citations are verified after completion. Interrupted streams retain clearly labeled partial output, and providers that respond with ordinary JSON instead of SSE still display a completed answer.

Building the semantic index sends corpus text to your embedding provider and can cost money. Node representations include speaker, conversation title, alternates and actual linked branch context. Batches are persisted and resumable. Provider identity is recorded per vector; a different model uses its own index. The source hash invalidates generated data when the corpus changes. V1 has a node index enriched with graph context; a separate window-vector index is not yet implemented. Similarity scans run locally and can take longer on large indexes. Provider credentials are required for semantic indexing and answers; these calls cannot be validated without your provider.

The agent can search, expand graph context, inspect a conversation (up to 200 lines), find related passages and query the original database with SELECT/CTE SQL. SQL uses a read-only connection, an authorizer, a 3-second execution deadline, and a 200-row cap. Context expansion is capped and displays immediate branch links, conditions, checks, modifiers and alternatives. Citation IDs are checked against retrieved evidence; this does not guarantee the model's interpretation, so use the source viewer to verify claims.

Saved evidence, reading size, line spacing, and brightness live in this browser's local storage. They are not synchronized between desktop and phone. The subdued default palette is intentional and follows the supplied accessibility references.

In **Saved evidence**, use **New folder** to organize snippets. Existing saved evidence remains in Unfiled. Choose **Select**, check snippets (or **Select all in this view**), then move them to a folder or remove them together. Bulk removal asks for confirmation and offers **Undo remove**, which remains available after a reload until used or replaced by another bulk removal. Folders can be renamed or deleted; deleting a folder moves its evidence to Unfiled. Organization remains local to this browser, like the evidence itself.

Use **Copy as Markdown** to paste the evidence locker into an LLM or **Download .md** to save `minnie-evidence.md`. Exports use selected snippets, or all snippets in the current folder view when nothing is selected. They group snippets by conversation, include speaker names and composite source IDs, and separate conversations with `- - -`. Conversation groups and their snippets retain their order from the evidence shelf; original dialogue text is preserved. If automatic clipboard access is blocked (including some mobile HTTP browsers), a selectable text dialog provides a manual-copy fallback. Export stays on your device and does not call a model.

## Prompt presets

Open **Presets** beside Reading to open the prompt side panel; use its close button or Escape to close it. Choose a named preset, create a copy with **New preset**, rename it in the editor, or delete it. At least one preset remains. **Save preset** saves the main research prompt, the separate no-search main prompt, and ordered instruction blocks. Your existing custom instructions automatically become the **Assistant persona** block on first use.

Add, remove, enable/disable, or reorder blocks. Each block can apply to archive research, no-search chat, or both. The citation-formatting block defaults to research only. The preview shows the assembled static prompt for either mode. Edits stay in the open page until saved; saving applies them to new responses. Presets and the active selection live in ignored `data/presets.json` on the host, shared by connected devices. Each response stores a prompt snapshot so retries keep the original instructions even if the preset is later edited or deleted.

The default instructions request individual source brackets and searches using ordinary terms as well as specialist language. Grouped citations such as `[28:353, 28:765]` are also supported directly: each source gets its own clickable button, including in older saved answers. Completed research validates every grouped ID against retrieved evidence and labels unavailable IDs as unverified. Citation validation establishes that a source was retrieved; it cannot guarantee that a model interpreted it correctly.

## Research chats

Archive responses are now conversations. Ask a follow-up in the composer beneath the answer; earlier questions, answers and cited evidence inform the next research pass. **New chat** starts a separate thread. All completed turns, reasoning, citations and research traces are saved in `data/chats.sqlite` on the host, independently of the disposable corpus index. The chat library is shared by browsers and phones connected to that same host. Each browser remembers its last open chat locally.

Open **Chats** or **Organize chats** to create folders, move chats, rename chats or folders, pin/unpin either, and delete. Deleting a folder keeps its chats in Unfiled; deleting a chat permanently deletes its turns after confirmation. Pending turns prevent overlapping responses in a chat and are marked interrupted after a server restart. Failed questions remain saved and can be retried by sending another message. A disconnected stream is recorded as an interrupted turn; its partial output is not saved as a completed answer. Existing unsaved responses from before this feature cannot be recovered.

Full history remains saved and readable; model context currently includes up to the latest 12 completed turns within a 48,000-character question/answer budget, plus their cited sources. Reasoning is displayed but not fed back as chat context. Fresh searches supplement the previous evidence, and prior assistant prose is not treated as independent canon.

Answers render Markdown while reasoning remains plain text. Markdown supports headings, emphasis, lists, quotes, code blocks, links and tables. Marked 18.0.14 and DOMPurify 3.4.16 are vendored and served locally, with no CDN dependency. HTML is sanitized, remote images are suppressed, and citations become source buttons outside links and code blocks. Numeric-only records and structural HUB nodes are excluded from search and new embeddings; valid semantic-only results still appear with a null lexical score. Structural nodes remain available in graph context.

In the research options, choose **No search** under Depth for general questions, editing, or formatting. This mode sends the question and completed chat history to the answer model without searching, embedding, expanding dialogue context, or offering database tools. It does not require an embedding provider. Answer length and enabled preset blocks still apply. Choose Quick, Research, or Exhaustive again to resume archive research.

The floating down button jumps to the bottom of a chat and appears when you scroll away from the end. It sits above the composer on desktop and mobile. **Stop** replaces Send while a response is running. Stopping closes the provider stream where possible, prevents further research rounds, and saves the latest server text as a labeled partial response; the provider may already be processing an in-flight request. Stopped partial answers are readable but are not fed back as completed chat context.

Research runs independently on the computer hosting Minnie. Switching to Discord, locking your phone, closing the viewer, or losing its stream does not cancel the research. When the page returns to the foreground it reconnects to the same job and catches up with the current answer, reasoning, and progress. Reopening a pending chat after a browser reload also resumes viewing it. Completed responses remain saved in chat history. No audio playback or music interruption is needed. Keep Minnie and its host computer running: shutting down/restarting the host still interrupts unfinished research. Provider failures remain errors with the existing retry option.

The centered response controls show **‹ Response 1 of 1 ›** even for a single answer. At the last alternative, the right caret acts as **Try again** and generates another response to the latest question using its original mode, answer length, and source filters. It keeps earlier responses rather than replacing them. Use the previous/next controls to compare alternatives, including after reopening the chat. The selected completed alternative is used for follow-up context. The copy icon at the left of each response row copies that selected answer as its original Markdown, including formatting and citation text. Reasoning and retrieval panels are excluded; when clipboard access is unavailable, the manual-copy dialog opens. Failed or stopped alternatives also remain available for comparison. Older chats retain their original answer when retried; comparison is disabled while a response is generating.

## Exploring dialogue branches

**Open dialogue context** follows outgoing database links in order, showing the spoken exchange until the next choice point. Select a dialogue choice to continue, or use **Previous branch** to go back. Structural HUB records are labeled as dialogue choice points instead of showing their placeholder `0`. Conditions, alternate lines, script effects, active checks and estimated passive skill requirements remain available. Minnie does not simulate your game state: conditional forks are shown as possible continuations, not silently chosen. Cycles and sequences longer than 100 linked nodes pause with an explicit continuation link.

**Copy context** copies the full text loaded in this modal, including the dialogue sequence, next choices, source IDs, and text inside collapsed conditions, alternates, effects and incoming-link sections. Action-button labels are omitted. It uses the same manual-copy fallback if clipboard access is unavailable.

## First semantic index

In **Settings → Embeddings**, enter your embedding provider's `/v1` base URL and API key, load models, and choose an embedding-capable model. Save that provider and use **Ping embedding provider** to verify it. Then select **Build semantic index** and keep Minnie running until it finishes. Interrupted builds resume when started again. Use the same provider URL and model for later searches. The app prepares its SQLite index automatically; no manual database conversion is needed. Building the index sends dialogue to the provider and may incur usage charges. Answer-model settings are separate.

## Data files

For the bundled database, a complete semantic index is **69,794 eligible dialogue vectors**, out of **112,827 archive records**. The remaining 43,033 structural HUB, empty, or non-dialogue records stay available in context but are excluded from search and new embeddings. Older builds may have around 112,826 stored vectors, including excluded records; that larger stored count is not the current completion target. Settings checks the actual eligible IDs for the selected provider and model, shows **Complete** or **Incomplete**, and reports how many are missing. Checking an already complete index makes no embedding requests.

Incomplete builds offer **Resume semantic index**. Progress updates in Settings and the terminal include ready/eligible counts, percentage, remaining vectors, and elapsed time. Provider failures show an HTTP code or connection/timeout explanation; the last build error survives a restart. Previously committed batches are retained. If a provider rate-limits the build, wait and resume with the same embedding settings.

The terminal reports startup inventory, build progress, completion, and errors without printing every polling request. Diagnostics also go to `data/minnie.log`, with up to three rotated backups. API keys and the phone access code are not written to this log. Include the relevant error lines when reporting a problem.

`source/` contains the extracted original DB and Ruby browser reference. The app opens the original database with `mode=ro`. `data/normalized.sqlite` contains the generated lexical index, metadata and vectors; `data/` is ignored by version control. The supplied source archives are retained.

## Verify

```powershell
python -m unittest discover -s tests -v
```

For evidence organization and export checks (requires Node.js):

```powershell
node tests/test_evidence.mjs
node tests/test_citations.mjs
node tests/test_research_stream.mjs
```

## Personal fonts and theme

Use **Settings → Custom stylesheet** to edit CSS and **Save stylesheet** to apply it immediately. Overrides load after the built-in styles and apply on desktop and phone. The enable switch lets you turn them off while keeping your CSS. They live in ignored `data/custom.css` (with the switch in `data/theme.json`), so normal Git pulls keep your tweaks. You can also edit `data/custom.css` directly and refresh the page.

For example, change the reading font:

```css
#query, #answer, .markdown-answer, .dialogue-text, .user-question, .reading-sample {
  font-family: "Palatino Linotype", Palatino, Georgia, serif;
}
```

Use fonts installed on each device, or supply your own `@font-face` / `@import` URL. Reading controls set `--text`, `--body-size` and `--leading` inline; an override such as `:root { --body-size: 21px !important; }` takes priority.

If a CSS experiment hides the controls, open `/?theme=default` on your Minnie address. This bypasses custom CSS for that page so you can repair or disable it in Settings, then return to the normal URL.
