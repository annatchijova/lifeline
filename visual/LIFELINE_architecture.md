# LIFELINE — Architecture Diagrams

> The map is not the decision. The person is.

Two views of the same system. The first is the **incident lifecycle** — the path a
piece of evidence travels from a field report to a sealed, verifiable decision.
The second is the **full module map** — every component, the data it owns, and the
three trust boundaries the design enforces: the deterministic core, the human
authority boundary, and the optional, read-only agent boundary.

---

## 1. Incident lifecycle (overview)

```mermaid
flowchart TD
    EV["Incoming evidence<br/><i>typed reports: requests, resources, shelters, routes</i>"]
    BR["Briefing<br/><i>human-readable incident view</i>"]
    VAL["Deterministic validators<br/><i>freshness · contradiction · duplicate · provenance gates</i>"]
    AL["Alerts<br/><i>attention feed · dispatch_authority: none</i>"]
    REV["Incident revisions<br/><i>append-only, hash-linked ledger</i>"]
    VG["Verification Graph<br/><i>supports · refutes · gaps · human actions</i>"]
    PK["Planning kernel<br/><i>eligible proposals from hard constraints</i>"]
    SIM["Simulations / alternatives<br/><i>declared what-if worlds, no winner chosen</i>"]
    HA{{"Human approval<br/><i>authenticated coordinator</i>"}}
    LED["Audit ledger<br/><i>hash-chained human decisions</i>"]
    EXP["Export + offline verification<br/><i>plan · GeoJSON · seals · CLI checks</i>"]

    EV --> BR --> VAL
    VAL --> AL
    VAL --> REV
    REV --> VG
    PK --> SIM
    REV --> PK
    VG --> PK
    PK --> HA
    VG --> HA
    HA -->|approve / reject| LED
    LED --> EXP

    classDef det fill:#0b3d4f,stroke:#39c0c8,stroke-width:1px,color:#e8fbff;
    classDef human fill:#5a2a82,stroke:#c79cff,stroke-width:2px,color:#f4ecff;
    classDef seal fill:#123a2a,stroke:#3ddc84,stroke-width:1px,color:#e6fff2;
    class EV,BR,VAL,AL,REV,VG,PK,SIM det;
    class HA human;
    class LED,EXP seal;
```

**Reading it:** evidence is validated deterministically (validators can only
*downgrade* a claim, never upgrade it); revisions and the Verification Graph feed
a planning kernel that emits **proposals, not dispatches**; an accountable human
approves or rejects; the decision is sealed into a tamper-evident ledger that can
be checked offline. No box in this chart sends a responder or ranks a human life.

---

## 2. Full module map with trust boundaries

```mermaid
flowchart TB
    subgraph SURFACE["Browser surfaces (web/)"]
        direction LR
        IDX["index.html<br/>bilingual landing"]
        ROOM["room.html<br/>synthetic incident map room"]
        OPS["ops.html<br/>authenticated ops console"]
        DEMO["demo/<br/>sealed static bundle"]
    end

    subgraph CORE["Deterministic core — reproducible, no floats in the decision path"]
        direction TB
        VALID["validators.py<br/>freshness · contradiction · input gates"]
        KERNEL["core.py<br/>planning kernel · hard constraints"]
        VERIF["verification.py<br/>sealed Verification Graph"]
        SIMU["simulate.py<br/>explicit alternative scenarios"]
        ALERT["alerts.py<br/>deterministic attention feed"]
        BRIEF["briefing.py<br/>human-readable briefing"]
        EXPORT["export.py<br/>plan · GeoJSON · seals"]
        TRACE["trace.py<br/>CRONOS-compatible trace"]
    end

    subgraph STATE["Persistence & identity"]
        direction LR
        INC["incidents.py<br/>SQLite · append-only<br/>hash-linked revisions"]
        AUTH["auth.py<br/>local operator roles<br/>reporter · coordinator · reader · admin"]
    end

    subgraph HUMAN["Human authority boundary"]
        APPROVE["approvals.py<br/>hash-chained decision ledger<br/>bound to exact plan seal"]
    end

    subgraph AGENT["Optional agent boundary — read-only, non-authoritative"]
        PACKET["Sealed, verified packet<br/><i>closed · read-only</i>"]
        OPENAI["OpenAI Responses API<br/><i>selects opaque citation IDs only</i>"]
        RENDER["Local controlled rendering<br/><i>fixed templates · sealed values</i>"]
    end

    CLI["__main__.py — CLI<br/>plan · verify · serve · operator · narrate"]
    SRV["server.py<br/>loopback incident backend"]

    %% surfaces to backend
    OPS -->|authenticated API| SRV
    ROOM -->|reads sealed artifacts| EXPORT
    SRV --> AUTH
    SRV --> INC

    %% CLI drives the core
    CLI --> VALID
    CLI --> KERNEL
    CLI --> SRV

    %% core data flow
    INC --> VALID
    VALID --> KERNEL
    VALID --> ALERT
    KERNEL --> VERIF
    KERNEL --> SIMU
    KERNEL --> BRIEF
    KERNEL --> EXPORT
    KERNEL --> TRACE
    VERIF --> EXPORT

    %% human decision
    KERNEL --> APPROVE
    VERIF --> APPROVE
    AUTH --> APPROVE
    APPROVE --> INC

    %% optional agent path (after a plan is sealed & verified)
    EXPORT --> PACKET
    VERIF --> PACKET
    PACKET --> OPENAI
    OPENAI -->|citation IDs only| RENDER
    RENDER --> ROOM
    RENDER --> OPS

    classDef det fill:#0b3d4f,stroke:#39c0c8,stroke-width:1px,color:#e8fbff;
    classDef human fill:#5a2a82,stroke:#c79cff,stroke-width:2px,color:#f4ecff;
    classDef agent fill:#4a3a12,stroke:#e0b83d,stroke-width:1px,color:#fff7e0;
    classDef ui fill:#1f2733,stroke:#7f93ad,stroke-width:1px,color:#e8eef5;
    classDef store fill:#123a2a,stroke:#3ddc84,stroke-width:1px,color:#e6fff2;

    class VALID,KERNEL,VERIF,SIMU,ALERT,BRIEF,EXPORT,TRACE,CLI,SRV det;
    class APPROVE human;
    class PACKET,OPENAI,RENDER agent;
    class IDX,ROOM,OPS,DEMO ui;
    class INC,AUTH store;
```

### The three boundaries, in one sentence each

- **Deterministic core (teal).** Produces eligible proposals from inspectable
  hard constraints — availability, capacity, medical compatibility, route status,
  provenance, freshness — with no floats in the decision path and every result
  sealed with SHA-256.
- **Human authority boundary (purple).** Only an authenticated coordinator can
  approve or reject a proposal, and each decision is hash-chained to the exact
  plan seal. The software never dispatches.
- **Optional agent boundary (amber).** After a plan is sealed *and* verified, a
  closed read-only packet may go to OpenAI, which returns only opaque citation
  IDs; LIFELINE renders every visible sentence locally from fixed templates. The
  model cannot invent a fact, change a record, or issue an instruction.
