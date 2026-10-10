# WorkFlowOS

## AI-Powered Desktop Workflow Automation Agent

WorkFlowOS is an **Agentic AI-powered desktop workflow automation system for Windows**. It allows users to describe high-level goals in natural language or demonstrate tasks through desktop interactions.

The system understands the user's intent, plans a sequence of actions, evaluates risk and confidence, performs safety checks, asks for user approval, executes the workflow, observes the result, and stores workflow history and feedback.

Unlike traditional automation scripts that rely on fixed mouse coordinates or manually written sequences, WorkFlowOS converts high-level user intentions into reusable and structured workflows.

---

## What Makes WorkFlowOS Agentic AI?

WorkFlowOS follows an **Agentic AI architecture** because it can move from a high-level goal to planning and real-world execution.

```text
User Goal
    |
    v
Understand Intent
    |
    v
Plan Actions
    |
    v
Risk & Confidence Assessment
    |
    v
Dry Run & Safety Checks
    |
    v
User Approval
    |
    v
Execute Tools / Actions
    |
    v
Observe Execution
    |
    v
Store History & Feedback
    |
    v
Improve Future Workflows
```

The system demonstrates the major characteristics of an AI agent:

- **Goal-oriented planning** — Converts a high-level goal into multiple executable actions.
- **Tool usage** — Uses semantic desktop automation actions to interact with the Windows environment.
- **Environment interaction** — Observes desktop activity and executes actions on files, applications, and UI elements.
- **Memory** — Stores workflows, versions, execution history, and user feedback.
- **Adaptation** — Uses workflow evolution and user corrections to improve future workflows.
- **Safety and guardrails** — Uses approval, sandbox execution, risk assessment, and protected system paths.

---

# Key Features

### 1. Chat to Automation

Users can provide instructions using natural language.

Example:

```text
Create a Placement folder and move all placement PDFs into it.
```

WorkFlowOS converts this instruction into a structured workflow.

---

### 2. Teach by Doing

Users can demonstrate a task instead of manually describing every step.

The `activity.py` module observes desktop activity such as:

- Keyboard input
- Mouse interactions
- Window focus
- Application launches

These activities are converted into high-level semantic actions.

---

### 3. AI Intent Compiler

The `ai.py` module acts as the intelligence layer.

It handles:

- Intent interpretation
- Workflow generation
- Risk scoring
- Confidence calculation
- Workflow evolution detection
- User feedback correction
- Workflow comparison

The AI produces a structured workflow rather than directly performing system operations.

---

### 4. One-Time Approval

WorkFlowOS does not require the user to approve every individual step.

Instead, the complete workflow is presented for review.

```text
+--------------------------------------+
|          WORKFLOW APPROVAL           |
|                                      |
| Goal: Organize Placement Documents  |
|                                      |
| 1. Create Placement folder           |
| 2. Search placement PDFs             |
| 3. Move PDFs to Placement            |
|                                      |
| Confidence: 95%                      |
| Risk: LOW                            |
|                                      |
|        [ ALLOW & RUN ]                |
|        [ CANCEL ]                     |
+--------------------------------------+
```

The user gives a single approval before execution.

If an action fails, execution stops immediately.

---

### 5. Dual Execution Environments

WorkFlowOS provides two execution environments.

#### Sandbox Mode

Workflows run inside an isolated `sandbox/` directory.

```text
sandbox/
├── Downloads/
├── Placement/
└── Reports/
```

This allows workflows to be tested without affecting real user files.

#### Real Desktop Mode

Approved workflows can interact with the actual Windows environment.

Examples include:

```text
notepad.exe
calc.exe
chrome.exe
```

Real Desktop Mode requires explicit user confirmation.

---

### 6. Workflow Lifecycle

The `workflow.py` module manages the complete workflow lifecycle.

```text
DRAFT
  |
  v
DRY_RUN
  |
  v
PENDING_APPROVAL
  |
  v
EXECUTING
  |
  v
COMPLETED
```

The workflow engine also manages:

- Dry-run simulation
- Safety checks
- Versioning
- Rollbacks
- Execution state
- Error handling

---

### 7. Workflow Evolution

WorkFlowOS supports workflow versioning.

For example:

```text
Version 1
Move files to Downloads
        |
        v
Version 2
Move files to Placement
```

The previous version remains available instead of being overwritten.

```text
v1 -> v2 -> v3 -> ...
```

This allows workflows to evolve while maintaining previous versions for rollback.

---

### 8. Correction and Feedback Memory

Users can correct the system.

Example:

```text
That was wrong. Move the files to Placement instead of Downloads.
```

The correction is stored in the `user_feedback` table.

Future workflow interpretation can use this feedback to improve the generated workflow.

---

# Agentic AI Architecture

WorkFlowOS can be understood through five major components of an agentic system.

| Agentic Capability | WorkFlowOS Implementation |
|---|---|
| Goal Understanding | `ai.py` |
| Planning | Intent Compiler and workflow generation |
| Tool Usage | `automation.py` |
| Environment Observation | `activity.py` |
| Memory | `database.py` |
| Execution | `automation.py` |
| Reflection / Feedback | Correction Engine |
| Adaptation | Workflow Evolution Engine |
| Safety | Risk scoring, sandbox, approval system |

---

# System Architecture

```text
                         USER
                           |
                           v
                 +-------------------+
                 |   FastAPI Web UI  |
                 |      app.py       |
                 +---------+---------+
                           |
             +-------------+-------------+
             |                           |
             v                           v
   +------------------+        +------------------+
   | Chat to          |        | Teach by Doing   |
   | Automation       |        |                  |
   +--------+---------+        +--------+---------+
            |                           |
            v                           v
       +---------+                +-------------+
       |  ai.py  |                | activity.py |
       +----+----+                +------+------+
            |                            |
            +-------------+--------------+
                          |
                          v
               +--------------------+
               | Unified Workflow   |
               | Plan (JSON)        |
               +---------+----------+
                         |
                         v
                +------------------+
                |   workflow.py    |
                | Lifecycle Engine |
                +--------+---------+
                         |
                         v
                +------------------+
                |     Dry Run      |
                | & Safety Checks  |
                +--------+---------+
                         |
                         v
              +---------------------+
              |  ONE-TIME APPROVAL  |
              |                     |
              |  ALLOW & RUN        |
              |  CANCEL             |
              +----------+----------+
                         |
                         v
              +---------------------+
              | Execution Environment|
              +----------+----------+
                         |
             +-----------+-----------+
             |                       |
             v                       v
      +-------------+        +--------------+
      | Sandbox     |        | Real Desktop |
      | Mode        |        | Mode         |
      +------+------+        +------+-------+
             |                      |
             +----------+-----------+
                        |
                        v
               +-----------------+
               | automation.py   |
               | Action Executor |
               +--------+--------+
                        |
                        v
               +-----------------+
               |   database.py   |
               | SQLite Storage  |
               +-----------------+
```

---

# Supported Semantic Actions

WorkFlowOS provides 18 semantic actions through the execution engine.

| # | Action | Description |
|---|---|---|
| 1 | `OPEN_APPLICATION` | Launches supported Windows applications |
| 2 | `OPEN_FOLDER` | Opens a folder |
| 3 | `OPEN_FILE` | Opens a file |
| 4 | `CREATE_FOLDER` | Creates directories |
| 5 | `CREATE_FILE` | Creates text files |
| 6 | `RENAME_FILE` | Renames files |
| 7 | `MOVE_FILE` | Moves files |
| 8 | `COPY_FILE` | Copies files |
| 9 | `DELETE_FILE` | Safely removes files |
| 10 | `SEARCH_FILES` | Searches for matching files |
| 11 | `READ_FILE` | Reads supported files |
| 12 | `CLICK` | Performs semantic UI clicks |
| 13 | `TYPE` | Performs keyboard input |
| 14 | `PASTE` | Pastes clipboard content |
| 15 | `DOWNLOAD` | Downloads remote resources |
| 16 | `UPLOAD` | Uploads documents |
| 17 | `SUBMIT` | Performs web/form submission |
| 18 | `SEND` | Sends messages or emails |

All operations pass through:

```python
automation.execute_action(action_dict)
```

---

# Example Workflow

### User Input

```text
Create a Reports folder and move all PDF files from Downloads into it.
```

### Processing

```text
User Goal
    |
    v
AI Intent Compiler
    |
    v
Generate Workflow
    |
    v
Calculate Risk & Confidence
    |
    v
Dry Run
    |
    v
Safety Checks
    |
    v
User Approval
    |
    v
Execute Actions
    |
    v
Record Result
```

### Example JSON Plan

```json
{
  "workflow_id": 1,
  "name": "Organize Placement Documents",
  "goal": "Create a Placement folder and move all placement PDF files into it",
  "confidence": 0.95,
  "risk_level": "LOW",
  "target_mode": "sandbox",
  "steps": [
    {
      "step_number": 1,
      "action_type": "CREATE_FOLDER",
      "target": "Placement",
      "parameters": {
        "path": "Placement"
      },
      "risk": "LOW"
    },
    {
      "step_number": 2,
      "action_type": "SEARCH_FILES",
      "target": "Downloads/*.pdf",
      "parameters": {
        "pattern": "*placement*.pdf"
      },
      "risk": "LOW"
    },
    {
      "step_number": 3,
      "action_type": "MOVE_FILE",
      "target": "Placement/",
      "parameters": {
        "source": "Downloads/*placement*.pdf",
        "destination": "Placement/"
      },
      "risk": "MEDIUM"
    }
  ]
}
```

---

# Security and Safety

Security is a core part of WorkFlowOS.

### Explicit User Consent

No workflow is executed before the user selects:

```text
ALLOW & RUN
```

### Protected Windows Paths

The following system directories are protected:

```text
C:\Windows
C:\Program Files
C:\Program Files (x86)
```

The automation engine blocks modification of these paths.

### Non-Destructive Deletion

Files are not permanently deleted.

Instead, they are moved to:

```text
.trash/
```

### Password Protection

Password fields and credential-related keystrokes are ignored during desktop recording.

---

# Project Structure

```text
WorkFlowOS/
│
├── app.py
│       FastAPI web application and API server
│
├── ai.py
│       Intent compiler, risk scoring,
│       confidence calculation and feedback logic
│
├── activity.py
│       Desktop activity observer and Teach Mode
│
├── workflow.py
│       Workflow lifecycle, dry-run,
│       versioning and rollback
│
├── automation.py
│       Semantic action execution engine
│
├── database.py
│       SQLite database and persistence layer
│
├── desktop_overlay.py
│       Windows desktop notification overlay
│
├── sandbox/
│       Isolated workflow testing environment
│
├── static/
│       Frontend assets
│
├── templates/
│       Web UI templates
│
├── requirements.txt
│       Python dependencies
│
├── .env.example
│       Environment variable template
│
└── README.md
```

---

# Database

WorkFlowOS uses **SQLite** for local persistence.

### Main Tables

```text
workflows
workflow_versions
actions
activity_logs
execution_history
user_feedback
```

The database stores:

- Workflow definitions
- Workflow versions
- Individual actions
- Activity logs
- Execution history
- User feedback
- Workflow state

---

# Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core application and automation logic |
| FastAPI | Backend API and web server |
| Vanilla JavaScript | Frontend interaction |
| HTML | Web interface structure |
| CSS | Web interface styling |
| SQLite | Workflow and execution persistence |
| PyAutoGUI | Desktop automation |
| PyWin32 | Windows-specific automation |
| AI / LLM | Intent understanding and workflow planning |
| Git | Version control |
| GitHub | Source-code hosting |

---

# Installation

## 1. Clone the Repository

```bash
git clone https://github.com/mansiharti/WorkFlowOS.git
```

## 2. Enter the Project Directory

```bash
cd WorkFlowOS
```

## 3. Create a Virtual Environment

```bash
python -m venv venv
```

## 4. Activate the Virtual Environment

For Windows:

```bash
venv\Scripts\activate
```

## 5. Install Dependencies

```bash
pip install -r requirements.txt
```

## 6. Configure Environment Variables

Copy:

```text
.env.example
```

to:

```text
.env
```

Add the required API credentials and configuration.

Do not upload `.env` or API keys to GitHub.

---

# Running the Application

Start the FastAPI server:

```bash
uvicorn app:app --reload
```

Then open the local application in your browser using the address provided by FastAPI.

---

# Project Objectives

The main objectives of WorkFlowOS are:

- Automate repetitive desktop tasks.
- Allow users to create workflows using natural language.
- Convert demonstrations into reusable workflows.
- Provide AI-based workflow planning.
- Execute actions through semantic tools.
- Provide safe execution through human approval.
- Support workflow versioning and rollback.
- Learn from user corrections.
- Reduce dependence on brittle coordinate-based automation.

---

# Future Enhancements

Potential future enhancements include:

- Scheduled workflow execution
- Voice-based workflow creation
- More desktop application integrations
- Advanced browser automation
- Improved workflow planning
- Cloud synchronization
- Multi-user support
- Workflow sharing
- Advanced execution analytics
- Additional AI models
- Improved error recovery
- Cross-platform support

---

# Project Information

**Project:** WorkFlowOS

**Type:** Agentic AI Desktop Automation System

**Platform:** Windows

**Backend:** Python + FastAPI

**Frontend:** Vanilla JavaScript, HTML, CSS

**Database:** SQLite

**Automation:** PyAutoGUI + PyWin32

**AI:** Large Language Model based intent and workflow planning

---

# License

This project is open-source and intended for educational, research, and development purposes.
