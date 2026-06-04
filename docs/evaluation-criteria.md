# Evaluation Criteria

## Drafter Agent

A good outreach draft:
- Is relevant to the campaign value proposition.
- References available lead context such as company, industry, or pain points.
- Uses no bracketed placeholders.
- Has a concrete call to action.
- Stays under the configured word limit.
- Includes no forbidden phrases or unsupported guarantees.

## Reviewer Agent

A good review result:
- Selects one of the generated draft types.
- Gives a concise rationale tied to the lead and campaign.
- Preserves the selected subject and body in a sendable form.
- Removes placeholders before returning the final body.

## Intent Extractor

A good intent classification:
- Uses one of the supported intent labels.
- Distinguishes meeting requests from meeting confirmations.
- Assigns low confidence to ambiguous messages.
- Classifies opt-out, bounce, and spam messages conservatively.

## Response Agent

A good inbound response:
- Directly addresses the sender's intent.
- Avoids unsupported claims.
- Does not say a calendar invite has already been sent.
- Ends with the required signature.
- Is complete and professional.

## Response Evaluator

A good evaluation:
- Rejects incomplete, unsafe, or misleading responses.
- Rejects false scheduling claims.
- Explains the rejection reason briefly.
- Approves only responses that are ready for the sender tool.

## Email Sender Agent

A good sender execution:
- Sends only the approved response text for simple replies.
- For meeting requests, proposes details and marks staff notification as tentative.
- For confirmations, marks staff notification as confirmed.
- Does not call a tool more than once per required step.
- Returns a structured action result.

## Meeting Details Generator

A good meeting proposal:
- Uses staff timezone and availability when present.
- Schedules no earlier than the configured delay.
- Avoids weekends.
- Produces subject, start time, duration, description, and conversation summary.

## Regression Tracking

Before changing prompts, run the offline unit tests and record representative manual or automated eval outcomes in `tests/eval/results/`. Prompt changes should not reduce personalization, safety, or routing accuracy.
