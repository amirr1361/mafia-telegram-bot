from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Phase(str, Enum):
    """فاز بازی؛ MANUAL = روایت دستی بدون جریان شبانه ربات."""

    LOBBY = "LOBBY"
    NIGHT = "NIGHT"
    DAY_DISCUSSION = "DAY_DISCUSSION"
    DAY_VOTE = "DAY_VOTE"
    MANUAL = "MANUAL"
    ENDED = "ENDED"


class Role(str, Enum):
    """Game roles; مافیا ساده / رئیس / مذاکره‌کننده share night kill as one faction."""

    MAFIA = "MAFIA"
    MAFIA_BOSS = "MAFIA_BOSS"
    MAFIA_NEGOTIATOR = "MAFIA_NEGOTIATOR"
    MAFIA_SIMPLE = "MAFIA_SIMPLE"
    MAFIA_SIMPLE_2 = "MAFIA_SIMPLE_2"
    DOCTOR = "DOCTOR"
    DETECTIVE = "DETECTIVE"
    ARMORED = "ARMORED"
    SNIPER = "SNIPER"
    JOURNALIST = "JOURNALIST"
    CITIZEN = "CITIZEN"
    # سناریوی بازپرس (مافیا)
    NATO = "NATO"
    SHIAD = "SHIAD"
    # سناریوی بازپرس (شهر)
    HUNTER = "HUNTER"
    INTERROGATOR = "INTERROGATOR"
    RUINTAN = "RUINTAN"
    # مافیا ساده (عمومی — بازپرس/تکاور)
    MAFIA_BASIC = "MAFIA_BASIC"
    # سناریوی تکاور
    KIDNAPPER = "KIDNAPPER"
    GUARD = "GUARD"
    GUNMAN = "GUNMAN"
    COMMANDO = "COMMANDO"
    # سناریوی ماسون (نقش‌های اختصاصی)
    GODFATHER = "GODFATHER"
    SABOTEUR = "SABOTEUR"
    SPY = "SPY"
    APACHE = "APACHE"
    NATASHA = "NATASHA"
    COWBOY = "COWBOY"
    COMMANDER = "COMMANDER"
    BODYGUARD = "BODYGUARD"
    MASON = "MASON"
    TAILOR = "TAILOR"
    PRIEST = "PRIEST"
    TOWN_SIMPLE = "TOWN_SIMPLE"
    # سناریوی نماینده
    DON_MAFIA = "DON_MAFIA"
    YAGHI = "YAGHI"
    HACKER_MAFIA = "HACKER_MAFIA"
    GUIDE = "GUIDE"
    MINELAYER = "MINELAYER"
    TOWN_LAWYER = "TOWN_LAWYER"
    SOLDIER = "SOLDIER"
    # ناظر بازی (فقط حالت بدون گرداننده؛ خارج از پخش نقش صندلی)
    OBSERVER = "OBSERVER"


@dataclass
class Player:
    user_id: int
    full_name: str
    username: str | None
    role: Role | None = None
    is_alive: bool = True
    """شماره صندلی ۱..n بعد از تأیید گرداننده (/confirmshuffle)."""
    seat: int | None = None
    """نقش روی کارت قبل از یاکوزای موفق (فقط سناریوی بازپرس)."""
    bazpors_original_role: Role | None = None
    bazpors_converted_by_yakuza: bool = False
    """نقش قبل از مذاکرهٔ موفق (فقط سناریوی مذاکره)."""
    mozakere_original_role: Role | None = None
    mozakere_converted_by_negotiation: bool = False
    """زرهٔ یک‌بارمصرف زره‌پوش (فقط سناریوی مذاکره)."""
    mozakere_armored_armor_used: bool = False

    @property
    def mention(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.full_name


@dataclass
class NightActions:
    mafia_target: int | None = None
    doctor_save: int | None = None
    detective_check: int | None = None


@dataclass
class Game:
    """A game room is keyed by room_code; all play happens in private chat with the bot."""

    room_code: str
    host_id: int
    # نام گرداننده هنگام ساخت اتاق (برای نمایش به بازیکنان)
    host_full_name: str = ""
    host_username: str | None = None
    phase: Phase = Phase.LOBBY
    day_count: int = 0
    scenario_name: str = "namayande"
    max_players: int = 10
    players: dict[int, Player] = field(default_factory=dict)
    votes: dict[int, int] = field(default_factory=dict)
    actions: NightActions = field(default_factory=NightActions)
    mafia_ids: set[int] = field(default_factory=set)
    """ترتیب موقت user_idها پس از /shuffle تا /confirmshuffle."""
    pending_seat_order: list[int] | None = None
    """تعداد شافل‌های پیاپی قبل از تأیید صندلی (نیمه‌خودکار / بدون گرداننده)."""
    bazpors_seat_shuffle_count: int = 0
    seats_finalized: bool = False
    roles_dealt: bool = False
    # پس از /endgame؛ دکمهٔ انتخاب برنده فقط برای گرداننده معتبر است
    host_may_pick_winner: bool = False
    # «auto» = ربات شب/روز؛ «manual» = بدون جریان شبانه ربات
    narration_mode: str | None = None
    """پیام «لابی پر شد» فقط یک‌بار برای گرداننده فرستاده شود."""
    lobby_full_notice_sent: bool = False
    """پیام وضعیت لابی (اتاق + لیست بازیکنان) برای ویرایش هنگام پیوستن دیگران."""
    lobby_status_message_ids: dict[int, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    """زمان پخش موفق نقش‌ها (شروع تایم‌اوت ۱۲ ساعته)."""
    roles_dealt_at: datetime | None = None
    """بازیکنانی که کارت تصویری نقش (با اسپویلر) برایشان رسیده است."""
    private_role_card_delivered_uids: set[int] = field(default_factory=set)
    """مسیر فایل JSONL رویدادهای بازی (عیب‌یابی)."""
    audit_log_path: str | None = None
    """رأی‌گیری پایان توسط بازیکنان: درخواست‌دهنده (نه گرداننده)."""
    player_end_initiator_id: int | None = None
    player_end_deadline: datetime | None = None
    player_end_approvals: set[int] = field(default_factory=set)
    """اسنپ‌شات بازیکنان هنگام شروع درخواست؛ گرداننده در این مجموعه نیست."""
    player_end_required_ids: set[int] | None = None
    """بعد از تأیید همه؛ این بازیکن مثل گرداننده برنده را انتخاب می‌کند."""
    player_end_winner_picker_id: int | None = None
    """تا قبل از تأیید دوم، پیام رأی برای همه فرستاده نشود."""
    player_end_broadcast_pending_uid: int | None = None
    player_end_broadcast_pending_at: datetime | None = None
    # مهلت‌ها هنگام ساخت اتاق از تنظیمات گرداننده کپی می‌شوند (پیش‌فرض هم‌ارز ثابت‌های سراسری ربات)
    lobby_fill_deadline_minutes: int = 20
    post_deal_timeout_hours: int = 12
    player_end_approval_minutes: int = 10
    player_end_broadcast_confirm_minutes: int = 10
    # بازپرس: manual | semi_auto | no_host (ربات گرداننده؛ سازنده بازیکن)
    bazpors_host_mode: str | None = None
    # گردانندگی نیمه‌خودکار بازپرس (فقط پیام به گرداننده؛ بدون ارسال به بازیکنان)
    bazpors_narrator_step: str | None = None
    bazpors_narrator_host_day: int = 0
    bazpors_narrator_night_count: int = 0
    bazpors_narrator_pending_uid: int | None = None
    bazpors_yakuzai_used: bool = False
    bazpors_nato_used: bool = False
    bazpors_doctor_self_save_count: int = 0
    """نجات خودی پزشک در همین شب (تا اعمال پایان شب قطعی نیست)."""
    bazpors_night_pending_doctor_self_save: bool = False
    """شمارندهٔ نجات خودی در شروع همین شب — برای بازگشت به مرحله قبل."""
    bazpors_night_baseline_doctor_self_saves: int = 0
    """مذاکره — شمارندهٔ نجات خودی پزشک (جدا از بازپرس)."""
    mozakere_doctor_self_save_count: int = 0
    mozakere_night_baseline_doctor_self_saves: int = 0
    """مذاکره — تعداد تیرهای استفاده‌شده تک‌تیرانداز."""
    mozakere_sniper_shots_used: int = 0
    """مذاکره — شمارندهٔ تیر در شروع همین شب (برای برگرداندن پس از مذاکره)."""
    mozakere_sniper_shots_used_at_night_start: int = 0
    """ماسون — شمارندهٔ نجات خودی پزشک (جدا از بازپرس/مذاکره)."""
    mason_doctor_self_save_count: int = 0
    mason_night_baseline_doctor_self_saves: int = 0
    mason_night_pending_doctor_self_save: bool = False
    mason_doctor_night_save_uids: list[int] = field(default_factory=list)
    """ماسون — گلوله‌های مصرف‌شده تک‌تیرانداز/فرمانده (در کل بازی)."""
    mason_sniper_bullets_spent: int = 0
    """ماسون — انتخاب شبانهٔ اسنایپر (حداکثر ۲ هدف)."""
    mason_sniper_night_selected_uids: list[int] = field(default_factory=list)
    """ماسون — اهداف تأییدشدهٔ فرمانده برای شلیک واقعی."""
    mason_commander_night_approved_uids: list[int] = field(default_factory=list)
    """ماسون — هدف شبانهٔ محافظ (محافظت روز بعد)."""
    mason_guardian_night_target_uid: int | None = None
    """ماسون — محافظت فعال محافظ در روز جاری (فقط در برابر آپاچی)."""
    mason_guardian_day_protection_uid: int | None = None
    """ماسون — هدف روزانهٔ آپاچی (پس از تأیید)."""
    mason_apache_day_target_uid: int | None = None
    mason_apache_day_pick_confirmed: bool = False
    """ماسون — آپاچی روزانهٔ خود را تأیید و اجرا کرده (محافظ دیگر نیازی به انتخاب ندارد)."""
    mason_apache_day_action_used: bool = False
    """ماسون — هدف روزانهٔ کابوی (پس از تأیید)."""
    mason_cowboy_day_target_uid: int | None = None
    mason_cowboy_day_pick_confirmed: bool = False
    """ماسون — هدف شبانهٔ تفنگدار (صاحب تفنگ روز بعد)."""
    mason_gunner_night_target_uid: int | None = None
    """ماسون — تفنگدار امشب کسی را برای تفنگ انتخاب نکرد."""
    mason_gunner_night_no_give: bool = False
    """ماسون — هدف شبانهٔ خرابکار."""
    mason_saboteur_night_target_uid: int | None = None
    """ماسون — خرابکار امشب کسی را خرابکاری نکرد."""
    mason_saboteur_night_no_sabotage: bool = False
    """ماسون — صاحب تفنگ روز جاری."""
    mason_day_gun_holder_uid: int | None = None
    mason_day_gun_sabotaged: bool = False
    mason_day_gun_used: bool = False
    """ماسون — تفنگ یک‌بار مصرف شده (پس از شلیک روز، تا پایان بازی)."""
    mason_gun_spent: bool = False
    """ماسون — هدف شلیک تفنگ روز (پس از استفاده)."""
    mason_day_gun_shot_target_uid: int | None = None
    """ماسون — اعضای زندهٔ تیم ماسون."""
    mason_team_member_ids: set[int] = field(default_factory=set)
    """ماسون — عضو جذب‌شدهٔ همین شب (ارزیابی پس از شب)."""
    mason_pending_recruit_uid: int | None = None
    mason_mason_night_no_recruit: bool = False
    """ماسون — دکمهٔ اختصاصی «تایلر» یک‌بار مصرف شده (جذب زنده یا انتخاب مرده)."""
    mason_tyler_button_consumed: bool = False
    """ناتویی ماسون — یک‌بار در کل بازی."""
    mason_nato_used: bool = False
    mason_nato_tonight: bool = False
    mason_nato_pending_role: str | None = None
    mason_nato_pending_target_uid: int | None = None
    mason_nato_confirmed: bool = False
    mason_nato_guess_role: Role | None = None
    mason_nato_guess_target_uid: int | None = None
    """ماسون — هدف شبانهٔ ناتاشا (سکوت روز بعد)."""
    mason_natasha_target_uid: int | None = None
    mason_natasha_pick_confirmed: bool = False
    """ماسون — هدف شبانهٔ کشیش (فقط در برابر سکوت ناتاشا)."""
    mason_priest_target_uid: int | None = None
    mason_priest_pick_confirmed: bool = False
    """ماسون — بازیکن سکوت‌شده در روز جاری."""
    mason_silenced_uid_for_day: int | None = None
    """ماسون — پنل‌های روزانهٔ آپاچی/کابوی پس از شب معارفه فعال‌اند."""
    mason_intro_day_ability_open: bool = False
    """ماسون — پس از شروع رأی‌گیری، پنل روزانه قفل می‌شود."""
    mason_intro_day_ability_locked: bool = False
    """ماسون — پنل کمک‌کننده «شروع رأی‌گیری» ارسال شده."""
    mason_vote_start_prompt_sent: bool = False
    """ماسون — منتظر تأیید کمک‌کننده برای شروع شب."""
    mason_night_start_prompt_sent: bool = False
    mason_night_start_pending_night: int | None = None
    """ماسون — بازیکنان بدون اقدام شبانه که اوکی زده‌اند."""
    mason_night_wait_ok_uids: list[int] = field(default_factory=list)
    """ماسون — تأیید پنل شبانهٔ نقش‌ها (no_host موازی)."""
    mason_night_doctor_confirmed: bool = False
    """پزشک — پنل باطل‌شدهٔ ناتویی منتظر اوکی است."""
    mason_night_doctor_nato_void_pending: bool = False
    mason_night_detective_confirmed: bool = False
    mason_night_sniper_confirmed: bool = False
    mason_night_commander_confirmed: bool = False
    mason_night_commander_panel_sent: bool = False
    mason_night_guardian_confirmed: bool = False
    mason_night_gunner_confirmed: bool = False
    mason_night_saboteur_confirmed: bool = False
    mason_night_mason_confirmed: bool = False
    mason_night_natasha_confirmed: bool = False
    mason_night_priest_confirmed: bool = False
    mason_night_entry_dispatched_night: int | None = None
    """ماسون — شب با اتمام اجباری بسته شده؛ callbackهای دیررس نادیده گرفته می‌شوند."""
    mason_night_force_finished: bool = False
    mason_apache_day_flow_active: bool = False
    mason_cowboy_day_flow_active: bool = False
    mason_apache_day_pending_uid: int | None = None
    mason_cowboy_day_pending_uid: int | None = None
    mason_night_resolution_applied: bool = False
    mason_last_night_had_collapse: bool = False
    """شب اولین فروپاشی تیم ماسون (برای بازنشستن مشورت پس از یک روز کامل)."""
    mason_collapse_night_number: int | None = None
    """پس از فروپاشی و گذشت یک روز کامل، از شروع رأی‌گیری آن روز به بعد."""
    mason_team_consultation_retired: bool = False
    mason_mafia_consult_prompt_sent: bool = False
    mason_mafia_consult_done: bool = False
    mason_team_consult_prompt_sent: bool = False
    mason_team_consult_done: bool = False
    mason_midday_step_prompt_sent: bool = False
    mason_midday_step_done: bool = False
    """ماسون — اسنپ‌شات اقدامات شب برای گزارش ناظر (قبل از پاک‌سازی state)."""
    mason_night_report_frozen: bool = False
    mason_night_report_doctor_save_uids: list[int] = field(default_factory=list)
    mason_night_report_sniper_selected_uids: list[int] = field(default_factory=list)
    mason_night_report_commander_approved_uids: list[int] = field(default_factory=list)
    mason_night_report_gunner_target_uid: int | None = None
    mason_night_report_guardian_target_uid: int | None = None
    mason_night_report_recruit_uid: int | None = None
    mason_night_report_no_recruit: bool = False
    mason_night_report_natasha_target_uid: int | None = None
    mason_night_report_natasha_pick_confirmed: bool = False
    mason_night_report_priest_target_uid: int | None = None
    mason_night_report_priest_pick_confirmed: bool = False
    mason_night_report_saboteur_target_uid: int | None = None
    mason_night_report_nato_guess_role: Role | None = None
    mason_night_report_nato_guess_target_uid: int | None = None
    mason_night_report_nato_tonight: bool = False
    """اخراج انضباطی همین شب (برای گزارش پایان شب)."""
    bazpors_night_discipline_kick_uid: int | None = None
    """اولین نفر انتخاب‌شده برای بازپرس در همان شب."""
    bazpors_interrog_pick_uid: int | None = None
    bazpors_yaku_sac_uid: int | None = None
    """عضو مافیا که برای فدای یاکوزا انتخاب شده (تا پایان مرحلهٔ یاکوزا)."""
    bazpors_yaku_sac_elim_uid: int | None = None
    """فدای یاکوزا؛ هنگام ثبت هدف مشخص می‌شود و در اعمال پایان شب حذف می‌گردد."""
    bazpors_yaku_night_civilian_uid: int | None = None
    """هدف یاکوزایی همین شب (برای گزارش کامل شب)."""
    bazpors_yaku_night_success: bool | None = None
    """زیرمرحلهٔ شب عادی وقتی bazpors_narrator_step == night_actions."""
    bazpors_night_substep: str | None = None
    """نقشی که در این شب از بازی خارج شده ولی نوبت بیدار شدنش است (NS_ROLE_ABSENT)."""
    bazpors_absent_night_role: str | None = None
    """در هر شب تازه صفر می‌شود؛ اگر مافیا ناتو زده باشد پزشک بیدار نمی‌شود."""
    bazpors_nato_action_registered: bool = False
    bazpors_nato_success: bool | None = None
    bazpors_nato_kill_target_uid: int | None = None
    bazpors_mafia_shot_registered: bool = False
    bazpors_detective_blocked: bool = False
    """آخرین نتیجهٔ استعلام کارآگاه برای نمایش به گرداننده در مرحلهٔ بعد."""
    bazpors_detective_last_answer: str | None = None
    """در NS_DET_ACK: استعلام مثبت (مافیا) یا منفی (شهروند)."""
    bazpors_det_ack_positive: bool = False
    bazpors_det_no_inquiry: bool = False
    bazpors_shiad_target_uid: int | None = None
    """بازیکنی که ناتو برای نقش حدس‌زده انتخاب/کشته شده (در صورت حدس درست)."""
    bazpors_nato_guess_target_uid: int | None = None
    """گزارش HTML کامل شب؛ بعد از اعمال پایان شب برای پنل صبح."""
    bazpors_night_report_html: str | None = None
    """شمارهٔ شبی که گزارش پایان شب برای ناظر ارسال شد (جلوگیری از تکرار)."""
    bazpors_observer_night_report_sent_night: int | None = None
    bazpors_assistant_night_report_sent_night: int | None = None
    """متن اضافهٔ یک‌بارمصرف قبل از پیام بعدی دستیار (مثلاً زنجیرهٔ هانتر)."""
    bazpors_host_flush_note: str | None = None
    bazpors_hunter_link_uid: int | None = None
    """آیا در همین شب (آخرین نوبت هانتر) وصل جدید ثبت شد — برای گزارش شب."""
    bazpors_hunter_linked_this_night: bool = False
    """هدف وصل هانتر در همین شب — برای گزارش (بعد از مرگ هانتر هم حفظ می‌شود)."""
    bazpors_hunter_report_link_uid: int | None = None
    """خط HTML زنجیرهٔ هانتر زیر بخش هانتر در گزارش شب."""
    bazpors_hunter_report_chain_line: str | None = None
    """متن اضافه فقط برای هانتر حذف‌شده وقتی زنجیره در شب مخفی است."""
    bazpors_elim_private_extra_html: dict[int, str] = field(default_factory=dict)
    bazpors_mafia_recruit_ids: set[int] = field(default_factory=set)
    """مذاکره — یک‌بار در بازی؛ پیوستگان مذاکره؛ وضعیت شب جاری."""
    mozakere_negotiation_used: bool = False
    mozakere_negotiation_tonight: bool = False
    mozakere_negotiation_target_uid: int | None = None
    mozakere_negotiation_success: bool | None = None
    mozakere_mafia_recruit_ids: set[int] = field(default_factory=set)
    """مذاکره — استعلام شبانه خبرنگار."""
    mozakere_journalist_target_uid: int | None = None
    mozakere_journalist_ack_positive: bool = False
    """بازیکنانی که با شلیک اسنایپر از بازی خارج شده‌اند — دیگر در شمار مافیا برای برد نمی‌آیند."""
    bazpors_sniper_eliminated_uids: set[int] = field(default_factory=set)
    bazpors_nato_guess_role: str | None = None
    """user_idها با ویرگول؛ مرحلهٔ انتخاب بین چند هم‌نقش برای ناتو."""
    bazpors_nato_multi_uids: str | None = None
    """نفر اول بازپرسی همین شب؛ اگر قبل از روز بمیرد، بازپرسی روز منتفی است."""
    bazpors_interrog_first_uid: int | None = None
    """بعد از شب، اگر True باشد در اولین پیام روز به گرداننده یادآوری شود و پاک شود."""
    bazpors_interrog_cancel_next_day: bool = False
    """جمله‌های آمادهٔ اعام به صندلی (ناتو، شات، یاکوزا، …) تا پایان شب."""
    bazpors_night_announce_lines: list[str] = field(default_factory=list)
    """زنده بودن هر بازیکن در شروع «اجرای نقش‌های شب» برای جملهٔ خداحافظی صبح."""
    bazpors_alive_at_night_start: dict[int, bool] | None = None
    """زنده بودن هر بازیکن در شروع روز (قبل از رأی روز) — برای گزارش شب."""
    bazpors_alive_at_day_start: dict[int, bool] | None = None
    """بعد از انتخاب نفر دوم بازپرس در شب True می‌شود."""
    bazpors_interrog_night_finished: bool = False
    bazpors_interrog_second_uid: int | None = None
    """صبح؛ اگر بازپرس شب را کامل کرده و منتفی نشده باشد."""
    bazpors_interrog_ready_for_day: bool = False
    """بعد از اولین روز با بازپرسی (ادامه یا انحلال)؛ شب‌های بعد مرحلهٔ بازپرس رد می‌شود."""
    bazpors_interrog_once_done: bool = False
    """بعد از پایان شب: ۳ نفر زنده و دقیقاً ۱ مافیا — روز فاز آشوب (Chaos)."""
    bazpors_ki_as_today: bool = False
    """دور فعلی دست دادن فاز آشوب — در callback برای رد دکمه‌های قدیمی."""
    bazpors_chaos_handshake_round: int = 0
    """انتخاب دست دادن: chooser_uid → target_uid (فقط همین دور)."""
    bazpors_chaos_choices: dict[int, int] = field(default_factory=dict)
    """برد مافیا از فاز آشوب — برای متن پایان بازی."""
    bazpors_mafia_win_via_chaos: bool = False
    bazpors_night_step_history: list[str] = field(default_factory=list)
    """چند بار هر بازیکن در رأی‌گیری انتهای روزهای قبل بوده (+۱ پس از پایان هر رأی روز)."""
    bazpors_day_vote_participations: dict[int, int] = field(default_factory=dict)
    """انتخاب موقت گرداننده در مرحلهٔ تیک (user_id با ویرگول)."""
    bazpors_day_vote_pick_uids: str | None = None
    """بازیکن‌های تأیید‌شده در رأی همین روز (قبل از پرسش خروج)."""
    bazpors_day_vote_defender_uids: str | None = None
    """tie_break | majority | tie_particip_pick — دلیل مرحلهٔ تأیید خروج روز."""
    bazpors_day_vote_elim_reason: str | None = None
    """منبع حذف آخرین مافیا هنگام برد شهروند: day_vote، interrog_vote، night_resolve، …"""
    bazpors_citizen_win_elim_source: str | None = None
    bazpors_citizen_win_elim_uid: int | None = None
    """تساوی مافیا/شهروند بلافاصله بعد از اعمال شب — گزارش شب قبل از اعلام تساوی."""
    bazpors_mafia_tie_after_night_report: bool = False
    """تک‌تیرانداز — یک‌بار در کل بازی."""
    bazpors_sniper_shot_used: bool = False
    """هدف شلیک تک‌تیرانداز در همین شب (اعمال در پایان شب)."""
    bazpors_sniper_night_target_uid: int | None = None
    """شلیک موفق اسنایپر به مافیا غیر رئیس — پیام تبریک در no_host و semi_auto."""
    bazpors_sniper_hero_mafia_kill: bool = False
    """کد ۴ رقمی ثبت ناظر (حالت no_host)."""
    observer_code: str | None = None
    """pending | code_sent | skipped | registered"""
    observer_prompt_status: str | None = None
    observer_user_id: int | None = None
    observer_full_name: str = ""
    observer_username: str | None = None
    """بازیکن کمک‌کننده ربات؛ فقط وقتی bazpors_host_mode == no_host پر می‌شود."""
    bot_assistant_user_id: int | None = None
    """پیام فعلی پنل دستیار/گرداننده — برای ویرایش درجا (مثلاً اخراج انضباطی)."""
    bazpors_assistant_panel_chat_id: int | None = None
    bazpors_assistant_panel_message_id: int | None = None
    """چند پنل همزمان با دکمه — کلید مرحله → (chat_id, message_id)."""
    bazpors_assistant_panel_refs: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )
    # بازپرس — انتخاب نقش توسط بازیکن‌ها بر اساس شمارهٔ مخفی
    bazpors_player_role_pick_active: bool = False
    bazpors_role_number_map: dict[int, str] = field(default_factory=dict)
    bazpors_role_number_claims: dict[int, int] = field(default_factory=dict)
    bazpors_player_role_claims: dict[int, dict[str, object]] = field(
        default_factory=dict
    )
    bazpors_role_pick_panel_messages: dict[int, tuple[int, int]] = field(
        default_factory=dict
    )
    bazpors_role_pick_started_at: str | None = None
    """پس از انتخاب همهٔ بازیکن‌های واقعی: تخصیص اتوماتیک به synthetic یک‌بار انجام شده."""
    bazpors_non_real_role_assignment_completed: bool = False
    # مذاکره — انتخاب نقش توسط بازیکن‌ها بر اساس شمارهٔ مخفی
    mozakere_player_role_pick_active: bool = False
    mozakere_role_number_map: dict[int, str] = field(default_factory=dict)
    mozakere_role_number_claims: dict[int, int] = field(default_factory=dict)
    mozakere_player_role_claims: dict[int, dict[str, object]] = field(
        default_factory=dict
    )
    mozakere_role_pick_panel_messages: dict[int, tuple[int, int]] = field(
        default_factory=dict
    )
    mozakere_role_pick_started_at: str | None = None
    mozakere_non_real_role_assignment_completed: bool = False
    # ماسون — انتخاب نقش توسط بازیکن‌ها بر اساس شمارهٔ مخفی
    mason_player_role_pick_active: bool = False
    mason_role_number_map: dict[int, str] = field(default_factory=dict)
    mason_role_number_claims: dict[int, int] = field(default_factory=dict)
    mason_player_role_claims: dict[int, dict[str, object]] = field(
        default_factory=dict
    )
    mason_role_pick_panel_messages: dict[int, tuple[int, int]] = field(
        default_factory=dict
    )
    mason_role_pick_started_at: str | None = None
    mason_non_real_role_assignment_completed: bool = False
    """آینهٔ پنل نریتور برای ناظر — ویرایش درجا به‌جای اسپم پیام جدید."""
    bazpors_observer_narrator_mirror_chat_id: int | None = None
    bazpors_observer_narrator_mirror_message_id: int | None = None
    bazpors_observer_narrator_mirror_refs: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )
    """شب معارفه توسط کمک‌کننده ربات شروع شده (no_host)."""
    no_host_intro_night_started: bool = False
    """پس از شب معارفه: انتخاب «بدون رأی» یا «پنل رأی» برای کمک‌کننده."""
    no_host_day1_vote_prompt_sent: bool = False
    no_host_day1_vote_resolved: bool = False
    """پنل انتخاب دفاعیهٔ روز اول (no_host) — pick | outcome | pick_elim | confirm_elim."""
    no_host_day1_defense_active: bool = False
    no_host_day1_defense_phase: str | None = None
    """بازیکن انتخاب‌شده برای حذف پس از «خروجی داشت» (قبل از تأیید)."""
    no_host_day1_pending_elim_uid: int | None = None
    """شب ۱ — انتخاب وصل هانتر توسط خود بازیکن (no_host)."""
    no_host_night1_hunter_flow_active: bool = False
    no_host_night1_hunter_done: bool = False
    no_host_hunter_pending_pick_uid: int | None = None
    no_host_hunter_awaiting_confirm: bool = False
    no_host_hunter_timer_gen: int = 0
    """شب ۱ — انتخاب عملیات مافیا (no_host)."""
    no_host_mafia_night1_flow_active: bool = False
    no_host_mafia_night1_done: bool = False
    """بازیکنانی که پنل عملیات/شات شب مافیا را می‌بینند."""
    no_host_mafia_night1_panel_uids: list[int] = field(default_factory=list)
    """اولین عضو panel_uids (لاگ/سازگاری)."""
    no_host_mafia_night1_chooser_uid: int | None = None
    no_host_mafia_night1_pending_action: str | None = None
    no_host_mafia_night1_chosen_action: str | None = None
    no_host_mafia_night1_actor_uid: int | None = None
    no_host_mafia_night1_refs: dict[int, tuple[int, int, str]] = field(
        default_factory=dict
    )
    """شب ۱ — انتخاب هدف شات پس از تأیید عملیات شات (no_host)."""
    no_host_mafia_shot_flow_active: bool = False
    no_host_mafia_shot_done: bool = False
    no_host_mafia_shot_pending_uid: int | None = None
    no_host_mafia_shot_awaiting_confirm: bool = False
    """شب ۱ — جریان یاکوزایی (no_host): sac | civ."""
    no_host_mafia_yaku_flow_active: bool = False
    no_host_mafia_yaku_done: bool = False
    no_host_mafia_yaku_phase: str | None = None
    no_host_mafia_yaku_pending_sac_uid: int | None = None
    no_host_mafia_yaku_pending_civ_uid: int | None = None
    """شب ۱ — ناتویی توسط بازیکن ناتو (no_host)."""
    no_host_mafia_nato_flow_active: bool = False
    no_host_mafia_nato_done: bool = False
    no_host_mafia_nato_phase: str | None = None
    no_host_mafia_nato_player_uid: int | None = None
    no_host_mafia_nato_pending_role: str | None = None
    no_host_mafia_nato_pending_target_uid: int | None = None
    """پنل مذاکره‌کننده — فقط سناریوی مذاکره (no_host)."""
    no_host_negotiator_flow_active: bool = False
    no_host_negotiator_pick_confirmed: bool = False
    no_host_negotiator_pending_tid: int | None = None
    """امضای آخرین پنل شبانهٔ نقش به بازیکن (no_host) برای جلوگیری از ارسال تکراری."""
    no_host_last_role_dm_signature: str | None = None
    """شمارهٔ شب که یادآوری قوانین رویین‌تن برایش فرستاده شده (no_host)."""
    no_host_ruintan_rules_sent_night: int | None = None
    no_host_ruintan_dm_signature: str | None = None
    no_host_ruintan_night_confirmed: bool = False
    no_host_citizen_night_batch_signature: str | None = None
    no_host_citizen_night_confirmed_uids: list[int] = field(default_factory=list)
    """پنل استعلام کارآگاه — امضای ارسال (no_host)."""
    no_host_detective_dm_signature: str | None = None
    no_host_detective_flow_active: bool = False
    no_host_detective_pick_confirmed: bool = False
    no_host_detective_pending_tid: int | None = None
    """شمارهٔ شب که نتیجهٔ استعلام به کارآگاه فرستاده شده."""
    no_host_detective_result_sent_night: int | None = None
    """پس از اعمال پایان شب — ارسال نتیجهٔ استعلام به کارآگاه (no_host)."""
    no_host_detective_result_pending: bool = False
    """پنل نجات پزشک — no_host."""
    no_host_doctor_dm_signature: str | None = None
    no_host_doctor_flow_active: bool = False
    no_host_doctor_pick_confirmed: bool = False
    no_host_doctor_nato_blocked_panel: bool = False
    no_host_doctor_pending_save_uids: list[int] = field(default_factory=list)
    """حداکثر یک نفر — نجات شبانهٔ پزشک (no_host)."""
    no_host_sniper_dm_signature: str | None = None
    no_host_sniper_flow_active: bool = False
    no_host_sniper_pick_confirmed: bool = False
    no_host_sniper_pending_target_uid: int | None = None
    no_host_sniper_result_sent_night: int | None = None
    no_host_sniper_result_pending: bool = False
    """پنل خبرنگار — فقط سناریوی مذاکره (no_host)."""
    no_host_journalist_dm_signature: str | None = None
    no_host_journalist_flow_active: bool = False
    no_host_journalist_pick_confirmed: bool = False
    no_host_journalist_pending_tid: int | None = None
    no_host_journalist_idle_confirmed: bool = False
    no_host_journalist_result_sent_night: int | None = None
    no_host_journalist_result_pending: bool = False
    no_host_shiad_dm_signature: str | None = None
    no_host_shiad_flow_active: bool = False
    no_host_shiad_pick_confirmed: bool = False
    no_host_shiad_pending_tid: int | None = None
    no_host_shiad_result_sent_night: int | None = None
    no_host_shiad_result_pending: bool = False
    no_host_night_entry_dispatched_night: int | None = None
    no_host_night_sage_dispatched_night: int | None = None
    no_host_sage_needs_observer_resync: bool = False
    no_host_interrog_wait_dm_signature: str | None = None
    no_host_interrog_dm_signature: str | None = None
    no_host_interrog_flow_active: bool = False
    no_host_interrog_pick_confirmed: bool = False
    """int1 | int2 | skip_ack"""
    no_host_interrog_ui_phase: str | None = None
    """جلسه بازپرسی روز — no_host."""
    no_host_interrog_day_phase: str | None = None
    no_host_interrog_day_session_signature: str | None = None
    """پنل «منتظر اوکی» دستیار در فاز session فقط یک‌بار ارسال شود."""
    no_host_interrog_day_assistant_wait_sent: bool = False
    no_host_interrog_day_ok_uids: list[int] = field(default_factory=list)
    no_host_interrog_day_decision: str | None = None
    no_host_interrog_day_pending_vote: int | str | None = None
    """استعلام وضعیت صندلی قبل از شروع روز — no_host."""
    no_host_table_inquiry_phase: str | None = None
    no_host_table_inquiry_pending: str | None = None
    no_host_table_inquiry_resolved_for_day: bool = False
    """پس از شب — منتظر تصمیم بازپرس (ادامه/انحلال) قبل از استعلام میز."""
    no_host_interrog_night_gate_pending: bool = False
    no_host_night_parallel_collect_active: bool = False
    bazpors_doctor_save_uids: list[int] = field(default_factory=list)
    """کمک‌کننده پنل دستیار رأی روز اول را می‌بیند (بدون پیام به بازیکنان)."""
    no_host_assistant_narrator_active: bool = False
    no_host_observer_only_narrator_mirror: bool = False
    """gate: day1_after_elim | after_night_before_day — پیشنهاد انتقال به semi_auto."""
    no_host_handoff_gate: str | None = None
    """پس از حذف — ارسال پیام «شما از بازی خارج شدید» (توسط flush)."""
    eliminated_notify_uids: list[int] = field(default_factory=list)
    """اولین کلیک روی دکمهٔ آینهٔ هر پیام (کلید ui_key → user_id کلیک‌کننده)."""
    mirror_action_claims: dict[str, int] = field(default_factory=dict)
    """ui_key → {text, player: (chat_id, msg_id), observer: (chat_id, msg_id)}."""
    mirror_prompt_messages: dict[str, dict[str, object]] = field(default_factory=dict)
