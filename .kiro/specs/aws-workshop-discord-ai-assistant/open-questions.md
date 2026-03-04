# Open Questions and Decisions: AWS Workshop Discord AI Assistant

## Critical Decisions Needed Before Implementation

### 1. Hosting Architecture: Lambda vs ECS Fargate

**Context**: The agent service can be deployed on either AWS Lambda or ECS Fargate.

**Lambda Pros**:
- Simpler deployment and management
- Built-in auto-scaling
- Pay-per-invocation pricing (cost-effective for sporadic traffic)
- No infrastructure management

**Lambda Cons**:
- 15-minute timeout limit (may be insufficient for complex multi-agent orchestration)
- Cold start latency (1-3 seconds for first request)
- More complex for long-running agent workflows
- Limited debugging capabilities

**ECS Fargate Pros**:
- No timeout limits (better for complex agent orchestration)
- Consistent performance (no cold starts)
- Better for long-running agent workflows
- Easier debugging and development
- More control over runtime environment

**ECS Fargate Cons**:
- More complex infrastructure setup
- Higher baseline cost (always running)
- Need to manage container images and scaling policies

**Recommendation**: Start with Lambda for MVP to validate the concept quickly. If timeout or cold start becomes an issue during testing, migrate to ECS Fargate. The agent code should be designed to be deployment-agnostic.

**Decision Required**: Confirm Lambda-first approach or go directly to ECS?

**Answer**: Agree with recomended approach

---

### 2. Discord MCP Server Availability

**Context**: The design assumes Discord MCP server is available for message search and posting.

**Questions**:
- Is there an existing Discord MCP server we can use?
- If not, do we need to build one from scratch?
- What's the expected latency for Discord message search?
- Should we implement direct Discord API integration as a fallback?

**Options**:
1. Use existing Discord MCP server (if available)
2. Build custom Discord MCP server
3. Implement direct Discord API integration without MCP layer

**Recommendation**: Evaluate existing Discord MCP implementations first. If none exist or meet requirements, implement direct Discord API integration for MVP and add MCP layer later if needed.

**Decision Required**: Which Discord integration approach should we use?

**Answer**: There shall be existing Discord MCP - please search and find it and we must make sure it has all functions that we are looking for to our system
---

### 3. AWS Docs MCP Server Availability

**Context**: The design assumes AWS Docs MCP server is available for documentation lookup.

**Questions**:
- Is there an existing AWS Docs MCP server?
- If not, should we build one or use alternative approaches?
- What's the coverage of AWS documentation we need?
- Should we use AWS documentation API directly?

**Options**:
1. Use existing AWS Docs MCP server (if available)
2. Build custom AWS Docs MCP server
3. Use web scraping with AWS documentation site
4. Use Bedrock Knowledge Base with AWS docs as data source
5. Rely on Claude's built-in AWS knowledge (no external docs)

**Recommendation**: For MVP, rely on Claude Sonnet's built-in AWS knowledge. Add AWS Docs MCP or Knowledge Base in Phase 2 if authoritative sourcing is needed.

**Decision Required**: Which AWS documentation approach should we use?

**Answer**: IMPORTANT!!! USE EXISTING AWS DOCS MCP SERVER - SEARCH ONLINE TO GATHER INFORMATION ABOUT IT. 
---

### 4. Query Expansion Quality Bar

**Context**: Discord search uses Nova Pro to expand questions into 7-15 keywords.

**Questions**:
- Is Nova Pro sufficient for quality keyword expansion?
- Should we use Claude Sonnet for better quality (higher cost)?
- Should we fine-tune a model specifically for this task?
- Is 7-15 keywords the right range, or should it be dynamic?

**Options**:
1. Nova Pro (fast, cheap, good enough for MVP)
2. Claude Sonnet (better quality, 3-5x more expensive)
3. Fine-tuned model (best quality, requires training data and time)
4. Dynamic depth based on question complexity

**Recommendation**: Start with Nova Pro and 7-15 keyword range. Evaluate quality with real workshop questions. Upgrade to Claude if quality is insufficient.

**Decision Required**: Confirm Nova Pro for MVP or require higher quality from start?

**Answer**: Nova shall be sufficient, I used it in another project for same exact task and it was working fine. Based on our Design we want query expansion depth to be configurable via Admin UI - if 7-15 keywords (keyphrases) will not be enough we will try to adjust it.

---

### 5. Cost Budget and Monitoring

**Context**: Bedrock usage costs vary significantly based on model choice and invocation frequency.

**Questions**:
- What's the budget per question?
- What's the total monthly budget?
- Should we implement aggressive cost controls?
- Should we limit Claude Sonnet usage more strictly?

**Cost Estimates** (approximate):
- Nova Pro: $0.0008 per 1K input tokens, $0.0032 per 1K output tokens
- Claude Sonnet: $0.003 per 1K input tokens, $0.015 per 1K output tokens
- Bedrock Knowledge Base: $0.10 per 1K queries

**Example Scenario** (100 questions/day for 30 days):
- FAQ searches: 3,000 queries × $0.0001 = $0.30
- Query expansion: 3,000 × Nova Pro = ~$5
- Discord searches: 3,000 × Nova Pro = ~$5
- Reasoning: 500 × Claude Sonnet = ~$50
- Total: ~$60-80/month

**Recommendations**:
- Set cost alert at $100/month
- Monitor cost per question metric
- Implement aggressive caching (can reduce costs by 25-40%)
- Prefer Nova Pro over Claude when quality is sufficient

**Decision Required**: Confirm budget and cost control strategy?

**Answer**:  Looks good - Agree on recommended approach!
---

### 6. FAQ Update Workflow

**Context**: Volunteers need to update FAQ content during workshops.

**Questions**:
- How often will FAQ be updated? (daily, weekly, per workshop?)
- Should updates be immediate or scheduled?
- Do we need FAQ versioning and rollback capability?
- Should we support incremental updates or full replacement only?

**Options**:
1. Immediate sync (update FAQ, trigger KB sync, wait 2-5 minutes)
2. Scheduled sync (batch updates, sync once per day)
3. Manual sync (volunteer triggers sync when ready)

**Recommendation**: Support immediate sync with async processing for MVP. Add versioning and rollback in Phase 2 if needed. Show sync status clearly in admin UI.

**Decision Required**: Confirm FAQ update workflow?
**Answer**: Can we make it configurable like daily, weekly, hourly. Also can we add ability to sync it per manual trigger.

---

### 7. User Feedback Mechanism

**Context**: Currently no way for students to rate answer quality.

**Questions**:
- Should we add thumbs up/down reactions to bot responses?
- Should we track which answers led to follow-up questions?
- How do we use feedback to improve FAQ?
- Should feedback be anonymous or attributed?

**Options**:
1. No feedback in MVP (simplest)
2. Thumbs up/down reactions (Discord native)
3. Detailed feedback form (more complex)
4. Implicit feedback (track follow-up questions)

**Recommendation**: Add thumbs up/down reactions in Phase 2. Use feedback to identify FAQ gaps and low-quality answers. Keep feedback anonymous.

**Decision Required**: Include feedback in MVP or defer to Phase 2?
**Answer**:  Agree on recommended approach
---

### 8. Multi-Language Support

**Context**: Design assumes English-only for MVP.

**Questions**:
- Do workshops support non-English speakers?
- Should FAQ be multilingual?
- Should bot detect question language and respond accordingly?
- What languages are needed?

**Recommendation**: English-only for MVP. Add i18n in Phase 2 if workshops expand internationally. Bedrock models support multiple languages natively, so adding this later is straightforward.

**Decision Required**: Confirm English-only for MVP?
**Answer**: Agree on recommended approach
---

### 9. Answer Caching Strategy

**Context**: Caching can significantly reduce costs and improve response times.

**Questions**:
- Should we cache identical questions?
- What's the appropriate TTL for cached answers?
- How do we invalidate cache when FAQ updates?
- Should we cache partial results (e.g., query expansions)?

**Current Design**:
- FAQ results: 5 minute TTL
- Discord results: 2 minute TTL
- Query expansions: 5 minute TTL
- Configuration: 5 minute TTL

**Concerns**:
- Stale answers if FAQ updates during cache TTL
- Students might get different answers for same question
- Cache invalidation complexity

**Recommendation**: Implement caching as designed. Invalidate FAQ cache immediately on FAQ update. Accept 2-5 minute staleness for Discord results (acceptable tradeoff for performance).

**Decision Required**: Confirm caching strategy and TTLs?
**Answer**: Agree on recommended approach

---

### 10. Rate Limiting Strategy

**Context**: Need to prevent abuse while allowing legitimate usage.

**Questions**:
- Is 20 questions per user per hour the right limit?
- Should limit vary by user role (student vs volunteer)?
- Should we implement global rate limits (questions per minute for entire system)?
- How do we handle legitimate power users?

**Current Design**:
- 20 questions per user per hour
- Admin can manually reset limits
- API Gateway throttling at 100 req/sec

**Recommendation**: Start with 20/hour for MVP. Monitor usage patterns. Adjust based on actual workshop behavior. Add role-based limits if needed.

**Decision Required**: Confirm rate limiting strategy?
**Answer**: Agree on recommended approach
---

### 11. Error Handling Philosophy

**Context**: When sources fail, should we fail gracefully or fail fast?

**Questions**:
- Should we always try to provide an answer, even if low quality?
- Should we skip failed sources or retry aggressively?
- Should we expose errors to students or hide them?
- How much degradation is acceptable?

**Current Design**:
- Graceful degradation (skip failed sources, continue waterfall)
- 3 retry attempts with exponential backoff
- Show warnings to students ("FAQ search temporarily unavailable")
- Always try to provide some answer

**Alternative**: Fail fast (return error if any critical source fails)

**Recommendation**: Stick with graceful degradation for MVP. Students prefer a partial answer over no answer. Monitor error rates and alert admins.

**Decision Required**: Confirm graceful degradation approach?
**Answer**: Agree on recommended approach

---

### 12. Testing Strategy Priorities

**Context**: Limited time for testing, need to prioritize.

**Questions**:
- What's the minimum acceptable test coverage?
- Should we prioritize unit tests or integration tests?
- Do we need property-based testing for MVP?
- How much manual testing is acceptable?

**Current Design**:
- 80% unit test coverage
- Integration tests for critical flows
- Property-based tests for core algorithms
- Manual testing for UX

**Recommendation**: Prioritize integration tests for critical flows (question → answer). Aim for 60% unit test coverage for MVP, increase to 80% post-launch. Property-based tests are nice-to-have.

**Decision Required**: Confirm testing priorities and coverage goals?
**Answer**: Agree on recommended approach
---

## Technical Clarifications Needed

### 13. AWS Strands Agents Framework

**Questions**:
- Is AWS Strands Agents production-ready?
- Are there any known limitations or issues?
- What's the learning curve for the team?
- Are there alternative frameworks we should consider?

**Decision Required**: Confirm Strands Agents or evaluate alternatives?
**Answer**: Strands is production ready framework and I tested it personally - lets stick with AWS Strands Agents Framework - please use connected strands-agents MCP server for documentation and examples
---

### 14. Discord Bot Permissions

**Questions**:
- Do we have admin access to the workshop Discord server?
- Can we create a bot and add it to the server?
- Are there any Discord server policies we need to follow?
- Should bot be visible in member list or hidden?

**Decision Required**: Confirm Discord server access and permissions?
**Answer**: We can get what we need - please research what creds will be needed.
---

### 15. Deployment Environments

**Questions**:
- How many environments do we need? (dev, staging, prod)
- Should each environment have separate Discord servers?
- What's the approval process for production deployments?
- Who has access to production?

**Recommendation**: Three environments (dev, staging, prod). Use separate Discord test servers for dev/staging. Require manual approval for prod deployments.

**Decision Required**: Confirm environment strategy?
**Answer**: IMPORTANT THIS IS MVP - ONLY DEV ENV FOR THIS IMPLEMENTATION

---

### 16. Volunteer Training

**Questions**:
- How much training will volunteers need for admin UI?
- Should we create video tutorials?
- Who provides support if volunteers have issues?
- Should we have a volunteer onboarding checklist?

**Recommendation**: Create written admin guide with screenshots. Add in-app help tooltips. Provide email support for volunteers.

**Decision Required**: Confirm volunteer training approach?
**Answer**: Lets only create written instructions for MVP part

---

## Success Metrics Validation

### 17. Success Criteria

**Questions**:
- Are the proposed success metrics the right ones?
- Who defines "success" for this project?
- How do we measure answer quality without user feedback?
- What's the minimum viable success for MVP?

**Proposed Metrics**:
- 80% of questions answered with confidence >= 0.75
- 95% of responses < 8 seconds
- 60% FAQ, 30% Discord, 10% Reasoning/Docs distribution
- 80% positive feedback (when implemented)

**Decision Required**: Confirm success metrics and targets?

**Answer**: IMPORTANT - SKIP SUCCESS METRICS FOR MVP IMPLEMENTATION - OUT OF SCOPE FOR NOW
---

## Next Steps

1. **Review and prioritize** these open questions
2. **Schedule decision meetings** with stakeholders
3. **Document decisions** in this file
4. **Update design and requirements** based on decisions
5. **Begin Phase 1 implementation** once critical decisions are made

## Decision Log

| Date | Question # | Decision | Decided By | Notes |
|------|-----------|----------|------------|-------|
| TBD  | 1         | TBD      | TBD        | TBD   |
| TBD  | 2         | TBD      | TBD        | TBD   |

---

**Last Updated**: [Date]
**Next Review**: [Date]
