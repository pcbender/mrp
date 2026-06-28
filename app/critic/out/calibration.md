# Critic Calibration Report

Generated: 2026-06-28 12:18

## Track Ranks

| Track | Expected | Actual | Drift | Note |
|-------|----------|--------|-------|------|
| pcbender--apa | 5 | 5 | ✓ | philosophical aria opener; sparse acoustic, Sisyphean lyric |
| pcbender--esmen | 4 | 4 | ✓ | high-energy standout; style/lyric peak of the Tria EP |
| pcbender--ousia | 4 | 4 | ✓ | meditative closer with soaring soprano |

## Album Records

| Album | Expected rank | Actual rank | Rank drift | Expected sum_vs_parts | Actual sum_vs_parts | Note |
|-------|---------------|-------------|------------|----------------------|---------------------|------|
| pcbender--tria | 4 | 4 | ✓ | greater | greater | ✓ · Tria EP — meditative 6-track EP, cohesive statement |

## Cohesion Thresholds (current calibration)

These are preliminary — calibrate against more albums before hardening.

| Verdict | Threshold | Basis |
|---------|-----------|-------|
| cohesive_statement | ≥ 0.85 | deferred — single album reference |
| varied | 0.65 – 0.85 | Tria EP: palette_consistency=0.79 |
| shuffle_playlist | < 0.65 | deferred — no reference yet |

To recalibrate, run `critic album <slug>` on additional releases and 
compare palette_consistency against subjective cohesion judgement.

## Approval Status

| Record | Type | Status |
|--------|------|--------|
| pcbender--aiteo | track | pending |
| pcbender--apa | track | pending |
| pcbender--ego-eimi | track | pending |
| pcbender--esmen | track | pending |
| pcbender--esti | track | pending |
| pcbender--joni | track | pending |
| pcbender--ousia | track | pending |
| pcbender--tria | album | pending |

**Result: PASS**
