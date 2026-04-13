# Project Guidelines

## Development Philosophy

We follow Spec-Driven Development (SDD) using OpenSpec.
The specification is the source of truth — not the code.

## Pipeline Roles

This project uses four-role pipeline via custom slash commands:

* `/project:pm` — Product Manager: requirements from client input
* `/project:architect` — Solution Architect: system design from requirements
* `/project:dev` — Developer: implementation from architecture
* `/project:test` — Tester: validation against requirements

## Workflow Rules

1. Never skip phases. PM → Architect → Dev → Tester, always.
2. Each phase produces artifacts in `openspec/changes/<change-name>/`.
3. All requirements must be traceable: every spec links to a requirement, every task links to a spec.
4. Use OpenSpec commands (`/opsx:propose`, `/opsx:apply`, `/opsx:archive`) for the overall lifecycle.
5. Use `/project:*` commands for role-specific deep work within each phase.

## Cost Control

* Use Sonnet for routine tasks (formatting, boilerplate, simple edits).
* Use Opus only for complex reasoning (architecture decisions, tricky debugging).
* Keep context clean: start fresh sessions for each phase.
* Commit after each phase completes — don't carry stale context.

## Code Standards

* Write tests before implementation (TDD).
* All public APIs must have documentation.
* No implementation without an approved spec.
* Every PR must reference its change folder.

## Commands Reference

Run `/project:pm`, `/project:architect`, `/project:dev`, or `/project:test` with your input to activate each role.
