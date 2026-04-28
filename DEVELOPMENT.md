# Development Guidelines & Project Plan

This document defines the behavioral standards and technical architecture for the EPL Telegram Broadcast system.

## 🛠 Behavioral Guidelines (Karpathy Principles)

To ensure code quality and maintainability, all development follows these four core principles:

### 1. Think Before Coding
- **No Assumptions**: Explicitly state assumptions. If uncertain, ask.
- **Surface Tradeoffs**: Present multiple interpretations if they exist.
- **Push Back**: If a simpler approach exists or a request is overcomplicated, suggest the alternative.

### 2. Simplicity First
- **Minimum Viable Code**: Implement only what is asked.
- **No Speculative Features**: No abstractions for single-use code or unnecessary "flexibility."
- **Aggressive Simplification**: If 200 lines can be 50, rewrite it.

### 3. Surgical Changes
- **Minimal Footprint**: Touch only the lines necessary to fulfill the request.
- **No Unsolicited Refactoring**: Do not "improve" adjacent code or formatting.
- **Style Matching**: Mimic existing patterns and naming conventions exactly.

### 4. Goal-Driven Execution
- **Verifiable Goals**: Transform tasks into "Step $\rightarrow$ Verify" loops.
- **Clear Success Criteria**: Define exactly what "done" looks like before implementation.

---

## 🏗 System Architecture

### Components
- **Data Source**: BBC Sport (Scraping) & FixtureDownload JSON (Schedules).
- **Database**: Supabase (PostgreSQL) - Stores fixtures and broadcast state.
- **Automation**: GitHub Actions (Scheduled runs every 30m).
- **Delivery**: Telegram Bot API.
- **Timezone**: All operations are normalized to Ethiopian Time (EAT / UTC+3).

### Broadcasting Logic
| Mode | Trigger | Condition | Output |
| :--- | :--- | :--- | :--- |
| **Daily** | 8 AM EAT | `DateEAT` == Today | Grouped match list in Amharic |
| **Reminders** | Every 30m | `DateEAT` within 60m AND status $\neq$ `reminded` | Upcoming match alert in Amharic |
| **Live Updates** | Every 30m | Score change OR Status == 'HT'/'FT' | Live goal/half-time/final alert in Amharic |
| **Results** | Every 30m | `DateEAT` == Today AND score exists AND status $\neq$ `result_sent` | Consolidated results roundup in Amharic |

## 📅 Roadmap
- [x] Basic JSON Import $\rightarrow$ SQLite
- [x] Telegram Integration
- [x] Amharic Localization
- [x] GitHub Actions Automation
- [x] Migration to Supabase
- [x] Live Score Logic (Goals/HT/FT)
- [ ] Heartbeat/System Health Monitoring
- [ ] Multi-source scraping fallbacks (Sky/Goal)
