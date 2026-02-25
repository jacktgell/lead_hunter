LEAD HUNTER DAEMON (LHD)
An Autonomous Agentic Framework for B2B Discovery

Lead Hunter Daemon is an autonomous, self-optimizing agentic system designed to mimic the intuition of a senior business development representative. Built with a decoupled infrastructure layer and a DSPy-driven "brain," LHD automates the entire lifecycle of lead acquisition—from boolean discovery to personalized SMTP outreach.

--------------------------------------------------------------------------------
🚀 ENGINEERING HIGHLIGHTS

* DSPy-Optimized Logic: Unlike fragile "prompt-engineering" based bots, LHD uses DSPy Signatures. This allows the system to be "compiled" and mathematically optimized against a dataset of successful leads, ensuring high conversion accuracy.

* Infrastructure-as-Code (IaC) Mindset: Features a custom GcpOllamaManager that handles the lifecycle of remote GPU instances via Google Cloud SDK, including secure IAP tunneling and automated VRAM warm-up.

* Observability: Integrated with GCP Cloud Logging for structured traceability and a real-time Pyvis Spider Graph that visualizes the agent's decision-making tree as it explores the web.

* Resilient Concurrency: Built to be thread-safe using threading.local browser contexts and SQLite write-ahead logging (WAL) to ensure data integrity during high-volume hunts.

--------------------------------------------------------------------------------
🏗️ SYSTEM ARCHITECTURE

LHD follows Hexagonal Architecture (Ports and Adapters) principles to ensure the core logic is independent of the tools used. 

[Core Pipeline] ===> [GCP Tunnel] ===> [Remote NVIDIA L4 GPU]
      ||
      |==> [Camoufox Browser]
      |==> [SQLite DB]
      |==> [SMTP Email Svc]

Layer Breakdown:
1. DOMAIN
   - Responsibility: Business logic & LLM Signatures
   - Technologies: DSPy, Pydantic

2. APPLICATION
   - Responsibility: Orchestration & Background Workers
   - Technologies: Python Threading, Queue

3. INFRASTRUCTURE
   - Responsibility: IO & External Integrations
   - Technologies: Playwright, GCP SDK, SQLModel

4. CORE
   - Responsibility: Configuration & Observability
   - Technologies: YAML, GCP Logging, Colorama

--------------------------------------------------------------------------------
🛠️ DEEP-TECH CHALLENGES & ENGINEERING SOLUTIONS

1. VRAM Cold-Boot Synchronization
   - Challenge: When the GCP instance boots, the OS reports a RUNNING status long before the Ollama service has successfully loaded the 32B model (approx. 19GB) into VRAM. Standard polling would timeout.
   - Solution: Developed an Application-Layer Settle-Logic. The daemon uses a tiered polling strategy that distinguishes between "Network Reachability" and "Model Readiness" (API returns 200 on /api/tags), ensuring hardware is fully primed before hunting.

2. State-Machine Visualization with Pyvis
   - Challenge: Most scrapers operate as a "black box," making it difficult to debug why an agent pruned a specific branch.
   - Solution: Integrated a Pyvis-based GraphTracker. By wrapping discovery in an atomic update-lock, the system generates a live HTML "Spider Graph." This visualizes memory nodes as "Pending," "Pruned," or "Converted," turning abstract LLM decisions into a traceable audit trail.

--------------------------------------------------------------------------------
💼 CONVERSION GUIDE (BUSINESS USE CASES)

LHD is highly adaptable. Modify "prompts.yaml" to pivot the agent to different markets:

1. Physical Products (Retail Stockists)
   - Target Intent: "Identify independent boutique retailers in London that sell handmade organic skincare."
   - Persona: Replace the profile with your brand's wholesale value prop.
   - Logic: The AI prioritizes "About Us" and "Stockists" pages to find buyer contact info.

2. Consulting & Contract Bidding
   - Target Intent: "Find Series A startups who just raised funding and lack a dedicated cybersecurity lead."
   - Logic: The agent prioritizes funding news and "Founding Engineer" job posts to pitch fractional CISO services.

--------------------------------------------------------------------------------
📊 MONITORING & CONTROL

LHD provides a Telegram Command Center for remote management:
* Live Statistics: Request real-time conversion rates and URL depth stats.
* Visual Discovery: Receive a PNG snapshot of the current Spider Graph.
* Deliverability Testing: Trigger a Mail-Tester integration to ensure SMTP headers (SPF/DKIM) pass spam filters.

--------------------------------------------------------------------------------
🚦 GETTING STARTED

Prerequisites:
- Python 3.13+
- Google Cloud SDK (configured with IAP permissions)
- Ollama (running locally or on managed GCP instance)

🐳 Docker Quickstart (Recommended):
This project includes a production-ready Dockerfile that handles the browser/scraper dependencies.

  1. Build the container:
     docker build -t lead-hunter .

  2. Run with GCP Credentials (for GPU Tunneling):
     docker run -it --env-file .env -v "$env:APPDATA\gcloud\application_default_credentials.json:/tmp/keys/gcp.json:ro" -e GOOGLE_APPLICATION_CREDENTIALS="/tmp/keys/gcp.json" lead-hunter

Local Installation:
  1. Clone the repository.
  2. Initialize environment: pip install .
  3. Configure secrets in .env (see .env.example).
  4. Define your persona in workspaces/cv_outreach/prompts.yaml.
  5. Compile the Brain: python scripts/optimize_agent.py
  6. Launch the Daemon: python main.py

--------------------------------------------------------------------------------

