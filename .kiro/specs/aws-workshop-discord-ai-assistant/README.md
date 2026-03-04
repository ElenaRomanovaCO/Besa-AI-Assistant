# AWS Workshop Discord AI Assistant - Specification

## Overview

This specification defines a multi-agent AI chatbot system for Discord that supports students during AWS workshops. The bot uses a confidence-ranked waterfall search strategy across multiple knowledge sources (FAQ, Discord history, LLM reasoning, AWS docs) to provide instant, contextual answers.

## Specification Documents

### 1. [design.md](./design.md) - Technical Design Document

**Purpose**: Comprehensive technical design with architecture, components, and interfaces

**Contents**:
- System architecture diagrams (Mermaid)
- Multi-agent system design (Orchestrator + 6 sub-agents)
- Component interfaces and responsibilities
- Data models and schemas
- Query expansion design
- FAQ Knowledge Base setup
- Discord MCP integration
- Admin UI specification
- Error handling strategies
- Testing approach
- Performance considerations
- Security considerations
- Infrastructure as Code (AWS CDK)

**Key Sections**:
- Architecture Overview (system diagram, sequence diagrams)
- 9 Core Components (Orchestrator, FAQ Agent, Discord Agent, AWS Docs Agent, Reasoning Agent, etc.)
- Waterfall Logic and Confidence Evaluation
- Query Expansion Design (7-15 keywords)
- FAQ Knowledge Base Setup (Bedrock KB, S3, ingestion pipeline)
- Discord Integration (MCP server, bot setup, slash commands)
- Admin UI (Next.js, 6 pages, API endpoints)
- Error Handling (7 scenarios with recovery strategies)
- Testing Strategy (unit, property-based, integration)
- Performance Optimization (caching, parallel queries)
- Security (authentication, authorization, data privacy)

**Use this document for**:
- Understanding system architecture
- Implementing components
- API contract reference
- Infrastructure setup

---

### 2. [requirements.md](./requirements.md) - Functional and Non-Functional Requirements

**Purpose**: Formal requirements derived from the design

**Contents**:
- 11 functional requirement sections (1.1 - 1.11)
- 8 non-functional requirement sections (2.1 - 2.8)
- Acceptance criteria (3.1 - 3.5)
- Constraints (4.1 - 4.10)
- Assumptions (5.1 - 5.10)
- Out of scope items (6.1 - 6.10)

**Key Requirements**:
- **1.1 Question Processing**: Waterfall logic, confidence thresholds, source attribution
- **1.2 FAQ Knowledge Base**: Semantic search, vectorization, S3 storage
- **1.3 Discord History Search**: Query expansion, keyword overlap ranking
- **1.4 LLM Reasoning**: Claude Sonnet for complex questions
- **1.6 Multi-Agent Architecture**: AWS Strands Agents with 6 sub-agents
- **1.7-1.9 Admin UI**: Configuration, FAQ management, logs, analytics
- **2.1 Performance**: 95% responses < 8s, caching strategy
- **2.3 Reliability**: 99% uptime, graceful degradation
- **2.4 Security**: Secrets Manager, IAM, VPC, encryption

**Use this document for**:
- Validating implementation completeness
- Writing test cases
- Stakeholder review
- Compliance verification

---

### 3. [tasks.md](./tasks.md) - Implementation Task Breakdown

**Purpose**: Phased task breakdown with dependencies

**Contents**:
- 5 implementation phases
- 28 major task groups
- 200+ individual tasks
- Dependencies between phases
- Estimated timeline

**Phases**:
1. **Phase 1**: Core Infrastructure and FAQ Agent (2-3 weeks)
   - Project setup, CDK infrastructure, FAQ agent, orchestrator, Discord integration, Lambda deployment
2. **Phase 2**: Discord Search and Query Expansion (1-2 weeks)
   - Discord MCP integration, query expansion, Discord agent
3. **Phase 3**: Reasoning and AWS Docs Agents (1-2 weeks)
   - Reasoning agent (Claude Sonnet), AWS Docs MCP, full waterfall
4. **Phase 4**: Admin UI (2-3 weeks)
   - Next.js setup, authentication, 6 admin pages, API backend
5. **Phase 5**: Production Readiness (1 week)
   - Performance optimization, security hardening, monitoring, documentation, deployment

**Total Timeline**: 7-11 weeks

**Use this document for**:
- Sprint planning
- Task assignment
- Progress tracking
- Dependency management

---

### 4. [open-questions.md](./open-questions.md) - Open Questions and Decisions

**Purpose**: Critical decisions needed before implementation

**Contents**:
- 17 open questions requiring decisions
- Options and recommendations for each
- Decision log template
- Next steps

**Critical Decisions**:
1. **Hosting**: Lambda vs ECS Fargate
2. **Discord MCP**: Use existing, build custom, or direct API?
3. **AWS Docs MCP**: Use existing, build custom, or rely on Claude?
4. **Query Expansion**: Nova Pro vs Claude Sonnet quality
5. **Cost Budget**: Monthly budget and cost controls
6. **FAQ Updates**: Immediate vs scheduled sync
7. **User Feedback**: Include in MVP or Phase 2?
8. **Multi-Language**: English-only or multilingual?
9. **Caching Strategy**: TTLs and invalidation
10. **Rate Limiting**: 20/hour appropriate?

**Use this document for**:
- Stakeholder decision meetings
- Risk identification
- Architecture decisions
- Scope clarification

---

## Quick Reference

### System Architecture

```
Student Question (Discord)
    ↓
Orchestrator Agent (Nova Pro)
    ↓
Waterfall Search:
    1. FAQ Agent (Nova Pro) → Bedrock Knowledge Base
       ├─ Confidence >= 0.75? → Return answer
       └─ Confidence < 0.75? → Continue
    2. Discord Agent (Nova Pro) → Discord MCP
       ├─ Expand query to 7-15 keywords
       ├─ Search configured channels
       ├─ Rank by keyword overlap
       ├─ Overlap >= 0.70? → Return answer
       └─ Overlap < 0.70? → Continue
    3. Reasoning Agent (Claude Sonnet)
       ├─ Synthesize answer from AWS knowledge
       ├─ Sufficient? → Return answer
       └─ Insufficient? → Continue
    4. AWS Docs Agent (Nova Pro) → AWS Docs MCP
       └─ Merge all results, rank, return
    ↓
Response (Discord thread)
```

### Key Technologies

- **Agent Framework**: AWS Strands Agents (Python)
- **LLM Models**: Amazon Bedrock Nova Pro (lightweight), Claude Sonnet (reasoning)
- **Knowledge Base**: Amazon Bedrock Knowledge Bases + S3
- **Database**: DynamoDB (configuration, logs)
- **Compute**: AWS Lambda or ECS Fargate
- **API**: API Gateway (REST)
- **Frontend**: Next.js + TypeScript + Tailwind CSS
- **Auth**: AWS Cognito
- **IaC**: AWS CDK (Python)
- **Testing**: pytest (Python), Jest (TypeScript)

### Configuration Defaults

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| FAQ Similarity Threshold | 0.75 | 0.5 - 1.0 | Minimum similarity score for FAQ match |
| Discord Overlap Threshold | 0.70 | 0.5 - 1.0 | Minimum keyword overlap for Discord match |
| Query Expansion Depth | 10 | 7 - 15 | Number of keywords to generate |
| Rate Limit | 20/hour | 1 - 100 | Max questions per user per hour |
| Log Retention | 90 days | 1 - 365 | Query log retention period |

### Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| FAQ Search | < 500ms | Bedrock KB query |
| Discord Search | < 2s | Including query expansion |
| LLM Reasoning | < 5s | Claude Sonnet synthesis |
| AWS Docs Search | < 3s | MCP query |
| End-to-End | < 8s (p95) | Full waterfall |

### Cost Estimates

**Per 100 Questions/Day (30 days = 3,000 questions)**:
- FAQ searches: ~$0.30
- Query expansion: ~$5
- Discord searches: ~$5
- Reasoning (500 invocations): ~$50
- **Total**: ~$60-80/month

**Cost Optimization**:
- Caching can reduce costs by 25-40%
- Prefer Nova Pro over Claude when possible
- Set cost alert at $100/month

### Admin UI Pages

1. **Dashboard**: Quick stats, recent questions, charts
2. **Configuration**: Thresholds, expansion depth, feature flags
3. **FAQ Management**: Upload, sync status, preview entries
4. **Channel Configuration**: Select searchable Discord channels
5. **Query Logs**: Searchable table, filters, CSV export
6. **Analytics**: Charts, cost breakdown, usage trends

### API Endpoints

**Discord Webhook**:
- `POST /discord/webhook` - Receive Discord events

**Admin API**:
- `GET /api/configuration` - Get current config
- `PUT /api/configuration` - Update config
- `POST /api/faq/upload` - Upload FAQ file
- `GET /api/faq/sync-status` - Check sync status
- `GET /api/faq/metadata` - Get FAQ metadata
- `GET /api/faq/entries` - List FAQ entries
- `GET /api/discord/channels` - List Discord channels
- `GET /api/logs/queries` - Get query logs
- `GET /api/analytics/overview` - Get analytics

### Slash Commands

- `/ask [question]` - Ask the AI assistant
- `/ask-private [question]` - Ask with ephemeral response
- `/faq [search]` - Search FAQ directly
- `/help` - Show bot usage instructions

## Getting Started

### For Implementers

1. Read [design.md](./design.md) for architecture understanding
2. Review [requirements.md](./requirements.md) for acceptance criteria
3. Check [open-questions.md](./open-questions.md) for pending decisions
4. Start with Phase 1 tasks in [tasks.md](./tasks.md)

### For Stakeholders

1. Review [requirements.md](./requirements.md) for scope and constraints
2. Make decisions on [open-questions.md](./open-questions.md)
3. Review [design.md](./design.md) architecture diagrams
4. Approve [tasks.md](./tasks.md) timeline and phases

### For Testers

1. Review acceptance criteria in [requirements.md](./requirements.md) section 3
2. Check testing strategy in [design.md](./design.md)
3. Follow test tasks in [tasks.md](./tasks.md) phases 1-5

## Document Status

| Document | Status | Last Updated | Reviewer |
|----------|--------|--------------|----------|
| design.md | ✅ Complete | [Date] | [Name] |
| requirements.md | ✅ Complete | [Date] | [Name] |
| tasks.md | ✅ Complete | [Date] | [Name] |
| open-questions.md | ⏳ Pending Decisions | [Date] | [Name] |

## Contact

- **Project Lead**: [Name]
- **Technical Lead**: [Name]
- **Product Owner**: [Name]

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | [Date] | Initial specification | Kiro AI |

---

**Specification ID**: 2c5a5f3b-7595-4428-ae6c-7be1f972d6f1  
**Workflow Type**: Design-First  
**Spec Type**: Feature
