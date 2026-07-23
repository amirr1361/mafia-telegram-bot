"""استعلام کارآگاه — re-export از bot.roles.detective (سازگاری عقب‌رو)."""

from __future__ import annotations

from bot.roles.detective import (
    DetectiveInquiryKind,
    DetectiveInquiryResult,
    block_inquiry_by_shiad as block_detective_inquiry_by_shiad,
    commit_pick as commit_detective_inquiry_pick,
    commit_shiad_voided_inquiry_note as commit_shiad_voided_detective_inquiry_note,
    committed_positive as detective_inquiry_committed_positive,
    evaluate_inquiry as evaluate_detective_inquiry,
    load_label_from_snapshot as load_detective_inquiry_label_from_snapshot,
    load_result as load_detective_inquiry_result,
    mark_no_inquiry as mark_detective_no_inquiry,
    result_label_fa as detective_inquiry_result_label_fa,
    target_reads_as_mafia_for_detective as _target_reads_as_mafia_for_detective,
    void_pick as void_detective_inquiry_pick,
)

__all__ = [
    "DetectiveInquiryKind",
    "DetectiveInquiryResult",
    "block_detective_inquiry_by_shiad",
    "commit_detective_inquiry_pick",
    "commit_shiad_voided_detective_inquiry_note",
    "detective_inquiry_committed_positive",
    "evaluate_detective_inquiry",
    "load_detective_inquiry_label_from_snapshot",
    "load_detective_inquiry_result",
    "mark_detective_no_inquiry",
    "detective_inquiry_result_label_fa",
    "void_detective_inquiry_pick",
]
