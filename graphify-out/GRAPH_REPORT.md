# Graph Report - mrp  (2026-06-17)

## Corpus Check
- 574 files · ~128,511,318 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1133 nodes · 1588 edges · 205 communities (198 shown, 7 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f27dade9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 126|Community 126]]
- [[_COMMUNITY_Community 132|Community 132]]
- [[_COMMUNITY_Community 133|Community 133]]
- [[_COMMUNITY_Community 134|Community 134]]
- [[_COMMUNITY_Community 135|Community 135]]
- [[_COMMUNITY_Community 136|Community 136]]
- [[_COMMUNITY_Community 137|Community 137]]
- [[_COMMUNITY_Community 138|Community 138]]
- [[_COMMUNITY_Community 139|Community 139]]
- [[_COMMUNITY_Community 140|Community 140]]
- [[_COMMUNITY_Community 141|Community 141]]
- [[_COMMUNITY_Community 142|Community 142]]
- [[_COMMUNITY_Community 143|Community 143]]
- [[_COMMUNITY_Community 144|Community 144]]
- [[_COMMUNITY_Community 145|Community 145]]
- [[_COMMUNITY_Community 146|Community 146]]
- [[_COMMUNITY_Community 147|Community 147]]
- [[_COMMUNITY_Community 148|Community 148]]
- [[_COMMUNITY_Community 149|Community 149]]
- [[_COMMUNITY_Community 155|Community 155]]

## God Nodes (most connected - your core abstractions)
1. `verify_target()` - 23 edges
2. `migration_inventory()` - 22 edges
3. `17. Work Packets` - 21 edges
4. `validate_repository()` - 19 edges
5. `main()` - 16 edges
6. `run_migration()` - 16 edges
7. `emit()` - 15 edges
8. `stage_build()` - 15 edges
9. `publish()` - 15 edges
10. `rollback()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `validate_schema()` --calls--> `Draft202012Validator`  [INFERRED]
  mrp/core/validate.py → tests/test_schemas.py
- `test_copy_referenced_assets_reports_missing_source_with_page_reference()` --calls--> `copy_referenced_assets()`  [EXTRACTED]
  tests/test_migrate_site.py → mrp/core/migrate_site.py
- `test_migration_inventory_accepts_artifact_root()` --calls--> `migration_inventory()`  [EXTRACTED]
  tests/test_migration_inventory.py → mrp/core/migration_inventory.py
- `test_migration_inventory_does_not_modify_source_files()` --calls--> `migration_inventory()`  [EXTRACTED]
  tests/test_migration_inventory.py → mrp/core/migration_inventory.py
- `test_migration_inventory_exclusions_are_explicit()` --calls--> `migration_inventory()`  [EXTRACTED]
  tests/test_migration_inventory.py → mrp/core/migration_inventory.py

## Import Cycles
- None detected.

## Communities (205 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.11
Nodes (41): ArgumentParser, add_common_command_options(), add_global_options(), build_parser(), emit(), main(), placeholder_result(), add_error() (+33 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (46): additionalProperties, type, type, type, additionalProperties, properties, type, $defs (+38 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (45): 10.1 Deploy Marker, 10.2 No Blind Delete, 10.3 Production Archive, 10.4 Machine-Readable Reports, 10. Safety Requirements, 11. Verification Policy, 12. Auto-Approval Policy, 13. Downstream Hooks (+37 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (42): artists, artist, getStaticPaths(), releases, ../components/ArtistCard.astro, ../components/Footer.astro, ../components/Header.astro, ../../components/ReleaseCard.astro (+34 more)

### Community 4 - "Community 4"
Cohesion: 0.05
Nodes (40): additionalProperties, type, additionalProperties, properties, required, type, type, type (+32 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (37): additionalProperties, format, type, format, type, pattern, type, $id (+29 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (32): additionalProperties, type, items, type, $id, pattern, type, additionalProperties (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.22
Nodes (25): copy_build(), copy_plan(), failed(), failed_build(), format_deployment(), load_targets(), now_utc(), resolve_build() (+17 more)

### Community 8 - "Community 8"
Cohesion: 0.09
Nodes (22): type, $ref, type, pattern, type, type, $ref, catalog_number (+14 more)

### Community 9 - "Community 9"
Cohesion: 0.20
Nodes (30): add_error(), clear_target(), copy_tree(), finish(), format_rollback(), now_utc(), rollback(), rollback_candidate() (+22 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (19): additionalProperties, minLength, type, minLength, type, $id, minLength, type (+11 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (17): type, type, type, type, minimum, type, type, duration (+9 more)

### Community 12 - "Community 12"
Cohesion: 0.33
Nodes (14): artist_url(), candidate_assets(), candidates_from_pages(), date_part(), format_import(), import_site(), load_json(), path_parts() (+6 more)

### Community 13 - "Community 13"
Cohesion: 0.36
Nodes (12): ContentCounts, count_assets(), count_content(), count_record_files(), detect_site_framework(), format_inspection(), inspect_deploy(), inspect_repository() (+4 more)

### Community 14 - "Community 14"
Cohesion: 0.15
Nodes (12): Assumptions, Chosen Site Framework, Content Migration Approach, Current Repository Structure, Decision Summary, Detected Constraints, Imported Content Shape, Imported Source Inventory (+4 more)

### Community 15 - "Community 15"
Cohesion: 0.38
Nodes (12): CompletedProcess, Path, rollback_repo(), run_mrp(), test_rollback_refuses_missing_marker(), test_rollback_requires_confirmation(), test_rollback_to_build_restores_and_verifies(), test_rollback_without_to_uses_latest_archive() (+4 more)

### Community 16 - "Community 16"
Cohesion: 0.26
Nodes (21): create_release(), failed(), release_record(), slugify(), track(), error_record(), load_content(), load_records() (+13 more)

### Community 18 - "Community 18"
Cohesion: 0.35
Nodes (11): Draft202012Validator, error_record(), load_schema(), load_yaml(), Path, test_invalid_migrated_page_and_post_samples_fail_validation(), test_invalid_release_samples_fail_validation(), test_schema_files_exist_and_are_valid() (+3 more)

### Community 19 - "Community 19"
Cohesion: 0.18
Nodes (11): minLength, type, description, seo, title, additionalProperties, properties, required (+3 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (11): dependencies, astro, js-yaml, name, private, scripts, build, dev (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.44
Nodes (10): publishable_repo(), CompletedProcess, Path, run_mrp(), test_publish_deploys_verifies_and_marks_release_live(), test_publish_refuses_missing_production_marker(), test_publish_refuses_unapproved_build(), write_file() (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.22
Nodes (20): classify_artist_release_routes(), classify_asset(), classify_post(), exclusion_summary(), format_migration_inventory(), load_json(), migration_inventory(), normalize_route() (+12 more)

### Community 23 - "Community 23"
Cohesion: 0.44
Nodes (9): deployable_repo(), CompletedProcess, Path, run_mrp(), test_stage_dry_run_reports_plan_without_copying(), test_stage_local_target_copies_build_and_writes_report(), test_stage_missing_marker_is_refused(), test_stage_refuses_remote_target_type() (+1 more)

### Community 24 - "Community 24"
Cohesion: 0.42
Nodes (11): minimal_repo(), CompletedProcess, Path, run_mrp(), test_invalid_migrated_page_fails_validation(), test_missing_artist_reference_fails(), test_missing_cover_image_fails_for_publishable_release(), test_validate_current_repo_writes_json_report() (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.47
Nodes (9): CompletedProcess, Path, run_mrp(), test_verify_missing_cover_image_fails(), test_verify_missing_release_page_fails(), test_verify_placeholder_token_fails(), test_verify_staging_passes_for_valid_local_target(), verified_repo() (+1 more)

### Community 26 - "Community 26"
Cohesion: 0.44
Nodes (8): CompletedProcess, Path, repo_with_verification(), run_mrp(), test_approve_build_must_match_latest_verified_build(), test_approve_verified_release_writes_record(), test_approve_without_verification_fails(), test_status_reads_latest_approval()

### Community 27 - "Community 27"
Cohesion: 0.42
Nodes (8): minimal_repo(), CompletedProcess, Path, run_mrp(), test_build_blocks_on_failed_validation(), test_build_creates_staging_artifact_and_report(), test_build_release_filter_passes_for_known_release(), test_build_skip_validate_reaches_static_build()

### Community 28 - "Community 28"
Cohesion: 0.47
Nodes (8): CompletedProcess, Path, run_mrp(), status_repo(), test_status_human_output_is_useful(), test_status_json_reports_release_and_latest_state(), test_status_unknown_release_fails_cleanly(), write_report()

### Community 29 - "Community 29"
Cohesion: 0.43
Nodes (7): CompletedProcess, run_mrp(), test_cli_runs_from_repo_root(), test_inspect_json_output_is_valid(), test_json_output_is_valid_for_build_command(), test_nested_release_create_command_is_registered(), test_unknown_command_fails_cleanly()

### Community 30 - "Community 30"
Cohesion: 0.50
Nodes (7): content_repo(), CompletedProcess, Path, run_mrp(), test_release_create_ep_adds_template_tracks(), test_release_create_refuses_overwrite(), test_release_create_single_writes_valid_draft_manifest()

### Community 31 - "Community 31"
Cohesion: 0.48
Nodes (6): minimal_repo(), CompletedProcess, Path, run_mrp(), test_import_site_does_not_modify_source_files(), test_import_site_generates_review_records_and_report()

### Community 32 - "Community 32"
Cohesion: 0.33
Nodes (5): Deployment, Happy Path, Required Markers, Rollback, Targets

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (6): type, additionalProperties, properties, type, allow_auto_publish, automation

### Community 34 - "Community 34"
Cohesion: 0.53
Nodes (5): ensure_markers(), json_command(), CompletedProcess, run_mrp(), test_v01_local_release_flow_end_to_end()

### Community 35 - "Community 35"
Cohesion: 0.40
Nodes (4): Agent Usage, Reports, Safe Release Workflow, Safety Rules

### Community 36 - "Community 36"
Cohesion: 0.40
Nodes (4): Artists, Content Model, Releases, Site

### Community 37 - "Community 37"
Cohesion: 0.40
Nodes (5): 17. Work Packets, Acceptance Criteria, MRP-004 — Implement MRP CLI Skeleton, Objective, Tasks

### Community 38 - "Community 38"
Cohesion: 0.40
Nodes (4): CLI, Docs, End-to-End Test, Maricopa Release Publisher

### Community 39 - "Community 39"
Cohesion: 0.40
Nodes (5): $ref, tracks, items, minItems, type

### Community 40 - "Community 40"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-001 — Repository Survey and Implementation Plan, Objective, Tasks

### Community 41 - "Community 41"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-002 — Create MRP Directory Structure, Objective, Tasks

### Community 42 - "Community 42"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-003 — Define Content Schemas, Objective, Tasks

### Community 43 - "Community 43"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-005 — Implement `mrp inspect`, Objective, Tasks

### Community 44 - "Community 44"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-006 — Implement Content Validation, Objective, Tasks

### Community 45 - "Community 45"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-007 — Normalize Existing Imported Content, Objective, Tasks

### Community 46 - "Community 46"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-008 — Create Site Shell, Objective, Tasks

### Community 47 - "Community 47"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-009 — Generate Pages from Content, Objective, Tasks

### Community 48 - "Community 48"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-010 — Implement `mrp build`, Objective, Tasks

### Community 49 - "Community 49"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-011 — Add Local Deployment Adapter, Objective, Tasks

### Community 50 - "Community 50"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-012 — Implement Staging Verification, Objective, Tasks

### Community 51 - "Community 51"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-013 — Implement Approval Records, Objective, Tasks

### Community 52 - "Community 52"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-014 — Implement Production Publish, Objective, Tasks

### Community 53 - "Community 53"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-015 — Implement Rollback, Objective, Tasks

### Community 54 - "Community 54"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-016 — Deferred Remote Deployment Adapter, Objective, Tasks

### Community 55 - "Community 55"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-017 — Add Release Creation Command, Objective, Tasks

### Community 56 - "Community 56"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-018 — Add Status Command, Objective, Tasks

### Community 57 - "Community 57"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-019 — Documentation Pass, Objective, Tasks

### Community 58 - "Community 58"
Cohesion: 0.50
Nodes (4): Acceptance Criteria, MRP-020 — End-to-End v0.1 Test, Objective, Tasks

### Community 62 - "Community 62"
Cohesion: 0.67
Nodes (3): pattern, type, artist_id

### Community 63 - "Community 63"
Cohesion: 0.67
Nodes (3): minLength, type, cover_image

### Community 64 - "Community 64"
Cohesion: 0.67
Nodes (3): enum, type, model

### Community 65 - "Community 65"
Cohesion: 0.67
Nodes (3): release_date, format, type

### Community 66 - "Community 66"
Cohesion: 0.67
Nodes (3): release_type, enum, type

### Community 67 - "Community 67"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 126 - "Community 126"
Cohesion: 0.10
Nodes (19): Acceptance Criteria, CLI Shape, MRP-101 - Migration Inventory Refresh, MRP-102 - Migration Schemas And Content Directories, MRP-103 - Implement `mrp migrate-site --dry-run`, MRP-104 - Generate Migrated Content Records, MRP-105 - Curated Asset Copy, MRP-106 - Astro Rendering For Migrated Pages (+11 more)

### Community 132 - "Community 132"
Cohesion: 0.08
Nodes (25): additionalProperties, $id, additionalProperties, properties, required, type, pattern, type (+17 more)

### Community 133 - "Community 133"
Cohesion: 0.10
Nodes (20): type, type, pattern, type, properties, content_html, excerpt, normalized_path (+12 more)

### Community 134 - "Community 134"
Cohesion: 0.17
Nodes (12): type, minLength, pattern, type, captured_path, id, status, type (+4 more)

### Community 135 - "Community 135"
Cohesion: 0.17
Nodes (12): type, type, properties, content_html, excerpt, seo, source, source_url (+4 more)

### Community 136 - "Community 136"
Cohesion: 0.17
Nodes (12): type, minLength, pattern, type, captured_path, id, system, type (+4 more)

### Community 137 - "Community 137"
Cohesion: 0.25
Nodes (8): $defs, seo, source, additionalProperties, type, additionalProperties, required, type

### Community 138 - "Community 138"
Cohesion: 0.25
Nodes (8): $defs, seo, source, additionalProperties, type, additionalProperties, required, type

### Community 139 - "Community 139"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 140 - "Community 140"
Cohesion: 0.29
Nodes (6): additionalProperties, $id, required, $schema, title, type

### Community 141 - "Community 141"
Cohesion: 0.33
Nodes (6): type, description, title, properties, minLength, type

### Community 142 - "Community 142"
Cohesion: 0.33
Nodes (6): type, description, title, properties, minLength, type

### Community 143 - "Community 143"
Cohesion: 0.40
Nodes (5): additionalProperties, required, type, properties, page

### Community 144 - "Community 144"
Cohesion: 0.40
Nodes (5): items, type, minLength, type, categories

### Community 145 - "Community 145"
Cohesion: 0.40
Nodes (5): additionalProperties, required, type, properties, post

### Community 146 - "Community 146"
Cohesion: 0.67
Nodes (3): pattern, type, normalized_path

### Community 147 - "Community 147"
Cohesion: 0.67
Nodes (3): slug, pattern, type

### Community 148 - "Community 148"
Cohesion: 0.67
Nodes (3): system, enum, type

### Community 149 - "Community 149"
Cohesion: 0.67
Nodes (3): status, enum, type

### Community 155 - "Community 155"
Cohesion: 0.13
Nodes (37): title_from_slug(), artist_record(), asset_references_from_html(), capture_assets_by_url(), copy_referenced_assets(), date_part(), extract_content_asset_references(), manifest_asset_type() (+29 more)

## Knowledge Gaps
- **435 isolated node(s):** `Namespace`, `Path`, `$schema`, `$id`, `title` (+430 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `migrate_site()` connect `Community 155` to `Community 0`, `Community 22`?**
  _High betweenness centrality (0.013) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 0` to `Community 7`, `Community 9`, `Community 12`, `Community 13`, `Community 16`, `Community 155`?**
  _High betweenness centrality (0.012) - this node is a cross-community bridge._
- **Why does `validate_repository()` connect `Community 16` to `Community 0`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **What connects `Maricopa Release Publisher.`, `MRP command-line interface.`, `Namespace` to the rest of the system?**
  _437 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.1101010101010101 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.043478260869565216 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.043478260869565216 - nodes in this community are weakly interconnected._