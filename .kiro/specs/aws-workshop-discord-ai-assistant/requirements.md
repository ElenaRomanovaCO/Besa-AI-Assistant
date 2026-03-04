# Requirements Document: AWS Workshop Discord AI Assistant

## 1. Functional Requirements

### 1.1 Question Processing

**1.1.1** The system SHALL accept student questions via Discord in a dedicated bot channel (#ask-besa-ai-assistant)

**1.1.2** The system SHALL accept student questions via Discord slash commands (/ask, /ask-private, /faq)

**1.1.3** The system SHALL respond to questions in threaded replies to maintain conversation context

**1.1.4** The system SHALL process questions through a confidence-ranked waterfall: FAQ → Discord History → LLM Reasoning → AWS Docs

**1.1.5** The system SHALL stop the waterfall when a high-confidence answer is found

**1.1.6** The system SHALL merge and rank results from multiple sources when no single source meets confidence threshold

**1.1.7** The system SHALL clearly indicate the source of each answer (FAQ, Discord History, AWS Docs, AI Reasoning)

**1.1.8** The system SHALL include confidence scores in responses

**1.1.9** The system SHALL respond within 90 seconds for 95% of queries

### 1.2 FAQ Knowledge Base

**1.2.1** The system SHALL maintain a vectorized FAQ knowledge base using Amazon Bedrock Knowledge Bases

**1.2.2** The system SHALL perform semantic similarity search against the FAQ using cosine similarity

**1.2.3** The system SHALL support FAQ uploads in CSV, JSON, and Markdown formats

**1.2.4** The system SHALL automatically sync FAQ updates to the Bedrock Knowledge Base

**1.2.5** The system SHALL return FAQ answers when similarity score >= configurable threshold (default 0.75)

**1.2.6** The system SHALL store FAQ documents in S3 with versioning enabled

**1.2.7** The system SHALL support FAQ entries with categories, questions, answers, and tags

### 1.3 Discord History Search

**1.3.1** The system SHALL search configured Discord channels for relevant past discussions

**1.3.2** The system SHALL expand student questions into 7-15 semantically related keywords before searching

**1.3.3** The system SHALL use Amazon Bedrock Nova Pro for query expansion

**1.3.4** The system SHALL rank Discord messages by keyword overlap percentage

**1.3.5** The system SHALL return Discord answers when overlap score >= configurable threshold (default 0.70)

**1.3.6** The system SHALL include thread context when relevant messages are part of a conversation

**1.3.7** The system SHALL provide links to original Discord messages in responses

**1.3.8** The system SHALL search only channels configured by volunteers via admin UI

### 1.4 LLM Reasoning

**1.4.1** The system SHALL invoke Claude Sonnet for reasoning only when FAQ and Discord return low-confidence results

**1.4.2** The system SHALL synthesize answers using Claude's AWS knowledge

**1.4.3** The system SHALL provide step-by-step reasoning when appropriate

**1.4.4** The system SHALL flag answers that require verification

**1.4.5** The system SHALL consider partial results from other sources as context for reasoning

### 1.5 AWS Documentation Search

**1.5.1** The system SHALL query AWS documentation when reasoning is insufficient or needs authoritative sourcing

**1.5.2** The system SHALL use AWS Docs MCP server for documentation lookup

**1.5.3** The system SHALL extract relevant documentation snippets

**1.5.4** The system SHALL include documentation URLs in responses

**1.5.5** The system SHALL merge documentation results with other source results when applicable


### 1.6 Multi-Agent Architecture

**1.6.1** The system SHALL implement a multi-agent architecture using AWS Strands Agents framework (python)

**1.6.2** The system SHALL include an Orchestrator Agent using Amazon Bedrock Nova Pro

**1.6.3** The system SHALL include a FAQ Sub-Agent using Amazon Bedrock Nova Pro

**1.6.4** The system SHALL include a Discord Sub-Agent using Amazon Bedrock Nova Pro

**1.6.5** The system SHALL include an AWS Docs Sub-Agent using Amazon Bedrock Nova Pro

**1.6.6** The system SHALL include a Reasoning Sub-Agent using Amazon Bedrock Claude Sonnet

**1.6.7** The system SHALL include an Online Search Sub-Agent using Amazon Bedrock Nova Pro (optional)

**1.6.8** The Orchestrator Agent SHALL coordinate all sub-agents and implement waterfall logic

**1.6.9** Each sub-agent SHALL be independently testable and replaceable

### 1.7 Admin UI - Configuration Management

**1.7.1** The system SHALL provide a Next.js web interface for volunteers for system configuration

**1.7.2** The system SHALL allow volunteers to configure FAQ similarity threshold (0.25 - 1.0)

**1.7.3** The system SHALL allow volunteers to configure Discord overlap threshold (0.25 - 1.0)

**1.7.4** The system SHALL allow volunteers to configure query expansion depth (default: 7 - 15 keywords)

**1.7.5** The system SHALL allow volunteers to select which Discord channels are searchable

**1.7.6** The system SHALL allow volunteers to enable/disable individual agents (Reasoning, AWS Docs, Online Search)

**1.7.7** The system SHALL allow volunteers to configure rate limiting (max queries per user per hour)

**1.7.8** The system SHALL persist configuration changes to DynamoDB

**1.7.9** The system SHALL apply configuration changes without requiring system restart

### 1.8 Admin UI - FAQ Management

**1.8.1** The system SHALL allow volunteers to upload FAQ files via drag-and-drop or file picker

**1.8.2** The system SHALL validate FAQ file format before processing

**1.8.3** The system SHALL display FAQ sync status (pending, syncing, completed, failed)

**1.8.4** The system SHALL show FAQ metadata (entry count, last updated, sync status)

**1.8.5** The system SHALL allow volunteers to preview FAQ entries in a table

**1.8.6** The system SHALL allow volunteers to download the current FAQ

**1.8.7** The system SHALL trigger Bedrock Knowledge Base sync after FAQ upload

### 1.9 Admin UI - Query Logs and Analytics

**1.9.1** The system SHALL log all questions with timestamp, user, question text, source, confidence, and response time

**1.9.2** The system SHALL provide a searchable query log table with filtering by date, source, user, and confidence

**1.9.3** The system SHALL allow volunteers to export query logs to CSV

**1.9.4** The system SHALL display analytics dashboard with questions per day, source distribution, and response times

**1.9.5** The system SHALL show cost breakdown by agent (Nova vs Claude invocations)

**1.9.6** The system SHALL retain query logs for 90 days (configurable)

**1.9.7** The system SHALL display real-time system health indicators

### 1.10 Authentication and Authorization

**1.10.1** The system SHALL use AWS Cognito for volunteer authentication

**1.10.2** The system SHALL support two roles: Admin (full access), User(only adjust configurable values) 

**1.10.3** The system SHALL require authentication for all admin UI pages as well as User UI pages.

**1.10.4** The system SHALL use HTTPS only for admin UI

**1.10.5** The system SHALL implement CORS restrictions for admin UI domain

### 1.11 Rate Limiting and Abuse Prevention

**1.11.1** The system SHALL limit users to configurable max queries per hour (default 20)

**1.11.2** The system SHALL return friendly error message when rate limit exceeded

**1.11.3** The system SHALL show remaining cooldown time in rate limit error

**1.11.4** The system SHALL allow admins to manually reset user rate limits

**1.11.5** The system SHALL implement API Gateway throttling at 100 requests/second

## 2. Non-Functional Requirements

<!-- ### 2.1 Performance

**2.1.1** The system SHALL respond to 95% of questions within 90 seconds end-to-end

**2.1.2** FAQ search SHALL complete within 500ms

**2.1.3** Discord search SHALL complete within 120 seconds including query expansion

**2.1.4** LLM reasoning SHALL complete within 120 seconds

**2.1.5** AWS Docs search SHALL complete within 180 seconds

<!-- **2.1.6** The system SHALL cache FAQ results for identical questions (5 minute TTL) -->

<!-- **2.1.7** The system SHALL cache Discord search results (2 minute TTL)

**2.1.8** The system SHALL cache query expansions for similar questions

### 2.2 Scalability

**2.2.1** The system SHALL support 50-100 concurrent students per workshop

**2.2.2** The system SHALL handle 10-20 questions per hour during peak usage

**2.2.3** The system SHALL support up to 500 FAQ entries

**2.2.4** The system SHALL search up to 10,000 Discord messages

**2.2.5** The system SHALL auto-scale to handle traffic spikes

### 2.3 Reliability

**2.3.1** The system SHALL have 99% uptime during workshop hours

**2.3.2** The system SHALL gracefully degrade when individual sources are unavailable

**2.3.3** The system SHALL continue waterfall when one source fails

**2.3.4** The system SHALL implement exponential backoff retry for transient failures (3 attempts)

**2.3.5** The system SHALL alert admins when sources are unavailable for > 10 minutes

**2.3.6** The system SHALL log all errors with sufficient detail for debugging -->
 

### 2.4 Security

**2.4.1** The system SHALL store Discord bot token in AWS Secrets Manager

**2.4.2** The system SHALL verify Discord webhook signatures for all incoming requests

**2.4.3** The system SHALL encrypt FAQ data at rest in S3

**2.4.4** The system SHALL use IAM roles for all AWS service access

**2.4.5** The system SHALL implement API Gateway WAF rules to prevent common attacks

**2.4.6** The system SHALL sanitize all user input to prevent injection attacks

**2.4.7** The system SHALL limit Discord bot permissions to required scopes only

**2.4.8** The system SHALL deploy Lambda functions in private VPC subnets

**2.4.9** The system SHALL use VPC endpoints for AWS service access

**2.4.10** The system SHALL implement automatic secret rotation for Discord bot token

### 2.5 Data Privacy

**2.5.1** The system SHALL NOT store personally identifiable information beyond Discord user IDs

**2.5.2** The system SHALL retain query logs for maximum 90 days

**2.5.3** The system SHALL clear search result caches every 5 minutes

**2.5.4** The system SHALL NOT store Discord message content beyond search cache

**2.5.5** The system SHALL enable S3 versioning for FAQ audit trail

**2.5.6** The system SHALL audit log all configuration changes with user and timestamp

### 2.6 Maintainability

**2.6.1** The system SHALL use Infrastructure as Code (AWS CDK) for all resources

**2.6.2** The system SHALL include comprehensive unit tests with 80% code coverage

<!-- **2.6.3** The system SHALL include integration tests for end-to-end flows

**2.6.4** The system SHALL include property-based tests for core algorithms -->

**2.6.5** The system SHALL use structured logging with correlation IDs

**2.6.6** The system SHALL include CloudWatch dashboards for monitoring

**2.6.7** The system SHALL document all APIs with OpenAPI/Swagger

**2.6.8** The system SHALL follow Python PEP 8 style guidelines

**2.6.9** The system SHALL use TypeScript for Next.js frontend

### 2.7 Cost Efficiency

**2.7.1** The system SHALL prefer Nova Pro over Claude Sonnet when quality is sufficient

**2.7.2** The system SHALL implement aggressive caching to reduce Bedrock invocations

**2.7.3** The system SHALL use DynamoDB on-demand pricing for cost optimization

**2.7.4** The system SHALL monitor cost per question metric

**2.7.5** The system SHALL alert when monthly cost exceeds $100

**2.7.6** The system SHALL log Bedrock invocation counts for cost tracking

### 2.8 Observability

**2.8.1** The system SHALL log all questions with full context

**2.8.2** The system SHALL track response time percentiles (p50, p95, p99)

**2.8.3** The system SHALL track error rate by source

<!-- **2.8.4** The system SHALL track cache hit rate -->

**2.8.5** The system SHALL track source distribution (% answered by each source)

**2.8.6** The system SHALL track Bedrock invocation counts by model

**2.8.7** The system SHALL create CloudWatch alarms for high error rates

**2.8.8** The system SHALL create CloudWatch alarms for high response times

## 3. Acceptance Criteria

### 3.1 Core Functionality

**3.1.1** Given a student asks a question in the bot channel, when the question matches an FAQ entry with confidence >= 0.75, then the bot responds with the FAQ answer within 2 seconds

**3.1.2** Given a student asks a question not in FAQ, when similar discussions exist in Discord history with overlap >= 0.70, then the bot responds with relevant Discord messages and links

**3.1.3** Given a student asks a question with no high-confidence matches, when the reasoning agent synthesizes an answer, then the bot responds with a reasoned answer clearly marked as "AI Reasoning"

**3.1.4** Given multiple sources return low-confidence results, when the orchestrator merges results, then the bot responds with top 3 ranked answers with clear source attribution

**3.1.5** Given a student uses /ask-private command, when the bot responds, then only the student sees the response (ephemeral message)

### 3.2 Admin Configuration

**3.2.1** Given a volunteer uploads a valid FAQ file, when the upload completes, then the FAQ is synced to Bedrock Knowledge Base and searchable within 5 minutes

**3.2.2** Given a volunteer changes the FAQ threshold to 0.80, when a student asks a question, then the new threshold is applied immediately

**3.2.3** Given a volunteer selects 3 Discord channels as searchable, when a student asks a question, then only those 3 channels are searched

**3.2.4** Given a volunteer sets query expansion depth to 12, when Discord search occurs, then exactly 12 keywords are generated

**3.2.5** Given a volunteer disables the Reasoning Agent, when no high-confidence answer is found, then the bot skips reasoning and goes directly to AWS Docs

### 3.3 Error Handling

**3.3.1** Given the FAQ Knowledge Base is unavailable, when a student asks a question, then the bot skips FAQ and continues to Discord search with a warning

**3.3.2** Given Discord MCP is unavailable, when a student asks a question, then the bot skips Discord search and continues to reasoning with a warning

**3.3.3** Given a user exceeds rate limit, when they ask another question, then the bot responds with remaining cooldown time

**3.3.4** Given Bedrock returns throttling error, when the system retries 3 times, then the bot skips that agent and continues waterfall

<!-- ### 3.4 Performance -->

<!-- **3.4.1** Given 100 questions asked during a workshop, when measuring response times, then 95% complete within 8 seconds

**3.4.2** Given identical questions asked within 5 minutes, when the second question is asked, then the cached result is returned within 1 second

**3.4.3** Given 20 concurrent questions, when the system processes them, then all receive responses without timeout errors -->

### 3.5 Security

**3.5.1** Given an unauthenticated user accesses admin UI, when they try to view any page, then they are redirected to login

**3.5.2** Given a Discord webhook with invalid signature, when it reaches the API, then it is rejected with 401 Unauthorized

**3.5.3** Given a user with Viewer role, when they try to update configuration, then the request is denied with 403 Forbidden

## 4. Constraints

**4.1** The system MUST use AWS Strands Agents framework (pyton) for multi-agent orchestration

**4.2** The system MUST use Amazon Bedrock for all LLM operations (no external LLM APIs)

**4.3** The system MUST use Amazon Bedrock Nova Pro for lightweight tasks (orchestration, query expansion, FAQ search, Discord search, AWS Docs search)

**4.4** The system MUST use Amazon Bedrock Claude Sonnet only for complex reasoning

**4.5** The system MUST use Discord MCP server for Discord integration

**4.6** The system MUST use AWS Docs MCP server for documentation lookup

**4.7** The system MUST deploy entirely on AWS infrastructure

**4.8** The system MUST use Next.js for admin UI frontend

**4.9** The system MUST use Python for agent backend

**4.10** The system MUST support only English language for MVP

## 5. Assumptions

**5.1** Discord MCP server is available or will be implemented as part of this project

**5.2** AWS Docs MCP server is available or will be implemented as part of this project

**5.3** Workshop volunteers have AWS accounts with appropriate permissions

**5.4** Discord server is already set up with appropriate channels

**5.5** Students have Discord accounts and access to the workshop server

**5.6** FAQ content is provided by workshop organizers

**5.7** Workshop duration is typically 1-3 days

**5.8** Peak usage is 10-20 questions per hour

**5.9** Budget allows for Bedrock usage at estimated scale

**5.10** Volunteers are comfortable with web-based admin interface

## 6. Out of Scope (Future Enhancements)

**6.1** Multi-language support (non-English questions and answers)

**6.2** User feedback mechanism (thumbs up/down on answers)

**6.3** Automatic FAQ generation from Discord discussions

**6.4** Voice channel integration

**6.5** Integration with other chat platforms (Slack, Teams)

**6.6** Advanced analytics with ML-based insights

**6.7** Custom fine-tuned models for query expansion

**6.8** Real-time Discord event streaming

**6.9** Automated FAQ quality scoring

**6.10** Integration with workshop lab environments
