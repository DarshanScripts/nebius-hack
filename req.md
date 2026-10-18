# Topic research for reel generation

## Goal

Accept a topic for a reel and use Tavily Research to gather a factual, cited research brief that can feed the reel generation step.

Example topic: **How does WhatsApp voice calling work behind the scenes? Explain the infrastructure.**

The research should explain the topic clearly, identify useful facts and visual ideas, and provide sources. For proprietary systems such as WhatsApp, distinguish publicly documented details from general industry practices and inferences. Do not present undocumented internal infrastructure as confirmed fact.

## Research workflow

1. Receive the reel topic.
2. Start a Tavily Research task with `POST https://api.tavily.com/research`, using `model: "pro"`, `stream: false`, and an `output_schema` for the research brief.
3. Store the returned `request_id`.
4. Poll `GET https://api.tavily.com/research/{request_id}` until the task completes or fails. While running, the status response can contain `status: "in_progress"`.
5. Pass the completed `content` and `sources` to the reel generation step. Handle a failed task without generating a reel from incomplete research.

## Example research input

```text
Research this topic for an educational reel:
How does WhatsApp voice calling work behind the scenes, including its infrastructure?

Explain the journey from tapping Call to hearing the other person's voice.
Investigate call setup and signaling, audio capture and compression, network
transport, NAT traversal and relays, encryption, and handling changing network
conditions. Explain technical terms in plain language.

Prioritize official WhatsApp/Meta engineering and security documentation and
relevant technical standards. Clearly distinguish confirmed WhatsApp behavior
from general VoIP techniques and reasonable inferences. Identify anything that
is not publicly known. Include a possible hook, the core explanation, key facts,
and visual ideas for a reel. Cite the factual claims.
```

## Tavily response format

These examples illustrate the response shape; they are not results from a live research run.

### Initial task response

```json
{
  "request_id": "123e4567-e89b-12d3-a456-426614174111",
  "created_at": "2026-10-18T10:30:00Z",
  "status": "pending",
  "input": "How does WhatsApp voice calling work behind the scenes?",
  "model": "pro",
  "response_time": 1.23
}
```

### Completed response

By default, `content` is a report string. When `output_schema` is supplied, `content` is a structured object matching that schema. `sources` contains the sources used in the research. Credit usage is optional and can be requested with `?include_usage=true`.

```json
{
  "request_id": "123e4567-e89b-12d3-a456-426614174111",
  "created_at": "2026-10-18T10:30:00Z",
  "status": "completed",
  "content": "# Research Report\n\nThe findings and analysis...",
  "sources": [
    {
      "title": "Example source",
      "url": "https://example.com/report",
      "favicon": "https://example.com/favicon.ico"
    }
  ],
  "response_time": 1.23,
  "usage": {
    "credits": 16
  }
}
```

## Proposed structured research output

Supply this `output_schema` in the research request. This is our application schema, not Tavily's default report format. Source URLs in the brief make individual claims traceable; Tavily also returns its top-level `sources` array.

```json
{
  "properties": {
    "topic": {
      "type": "string",
      "description": "The reel topic being researched."
    },
    "summary": {
      "type": "string",
      "description": "A plain-language explanation of the topic for an educational reel."
    },
    "hook": {
      "type": "string",
      "description": "A short, accurate opening that makes the topic interesting without exaggeration."
    },
    "explanation_steps": {
      "type": "array",
      "description": "Ordered steps explaining how the system or concept works.",
      "items": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "explanation": { "type": "string" },
          "visual_idea": { "type": "string" },
          "evidence_type": {
            "type": "string",
            "description": "Use documented, general_industry_practice, or inference."
          },
          "source_urls": {
            "type": "array",
            "items": { "type": "string" }
          }
        },
        "required": ["title", "explanation", "visual_idea", "evidence_type", "source_urls"]
      }
    },
    "key_facts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "fact": { "type": "string" },
          "source_urls": {
            "type": "array",
            "items": { "type": "string" }
          }
        },
        "required": ["fact", "source_urls"]
      }
    },
    "uncertainties": {
      "type": "array",
      "description": "Details that are unknown, disputed, inferred, or not publicly documented.",
      "items": { "type": "string" }
    }
  },
  "required": ["topic", "summary", "hook", "explanation_steps", "key_facts", "uncertainties"]
}
```

## References

- [Tavily: Create Research Task](https://docs.tavily.com/documentation/api-reference/endpoint/research)
- [Tavily: Get Research Task Status](https://docs.tavily.com/documentation/api-reference/endpoint/research-get)
