"""Regression: inline callback buttons must map to a handler path."""

from __future__ import annotations

import unittest

from bot.chaos_handshake import chaos_handshake_mirror_act_active
from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.no_host_citizen_night import no_host_citizen_act_active
from bot.no_host_detective_night import no_host_detective_act_active
from bot.no_host_doctor_night import no_host_doctor_act_active
from bot.no_host_interrog_day import no_host_interrog_day_act_active
from bot.no_host_interrogator_night import no_host_interrog_act_active
from bot.no_host_journalist_night import no_host_journalist_act_active
from bot.no_host_mafia_nato import mafia_nato_act_active
from bot.no_host_mafia_night1 import mafia_night1_act_active
from bot.no_host_mafia_shot import mafia_shot_act_active
from bot.no_host_mafia_yaku import mafia_yaku_act_active
from bot.no_host_mozakere_negotiation import mozakere_negotiator_act_active
from bot.no_host_night1 import hunter_night1_act_active
from bot.no_host_night_common import no_host_night_wait_ok_act_active
from bot.no_host_ruintan_night import no_host_ruintan_act_active
from bot.no_host_shiad_night import no_host_shiad_act_active
from bot.no_host_sniper_night import no_host_sniper_act_active
from bot.bazpors_narrator import BazporsNarrCb
from bot.chaos_handshake import CHAOS_DAY_HANDSHAKE, ChaosHandshakeCb
from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY
from bot.main import (
    AmirHostDoc,
    CreatePickHostMode,
    CreatePickPlayers,
    CreatePickScenario,
    HostPanel,
    HubMenu,
    JoinConfirmCb,
    MedalPick,
    NoHostBotAssistantPick,
    NoHostDay1DefenseCb,
    NoHostIntroNightStart,
    NoHostObserverPrompt,
    PlayerEndApprove,
    PlayerEndBroadcastConfirm,
    PlayerEndDismiss,
    SemiAutoDevLobby,
)
from bot.observer_delivery import PlayerMirrorCb
from bot.post_game_flow import EndGameAbortConfirm, EndGameDismiss, EndGamePick
from bot.post_game_rating import RateHostSkip, RateHostStars


NO_HOST_MIRROR_ACTS: frozenset[str] = frozenset(
    {
        "nms",
        "nmy",
        "nmn",
        "nmc",
        "nmb",
        "nmg",
        "msk",
        "msc",
        "msb",
        "ysp",
        "ysc",
        "ysb",
        "ycp",
        "ycc",
        "ycb",
        "n1c",
        "n1b",
        "n2p",
        "n2c",
        "n2b",
        "n1r-CITIZEN",
        "negp",
        "negc",
        "negb",
        "hnp",
        "hns",
        "hnc",
        "hnb",
        "sgt",
        "sgc",
        "sgb",
        "ndp",
        "ndc",
        "ndb",
        "dkt",
        "dkn",
        "dkc",
        "dkb",
        "dko",
        "ihok",
        "ihco",
        "ihdi",
        "nii1",
        "nii1s",
        "nii2",
        "nii2a",
        "nii2r",
        "niisk",
        "skt",
        "skn",
        "skc",
        "skb",
        "jic",
        "jrp",
        "jrc",
        "jrb",
        "ruc",
        "nwok",
        "cic",
    }
)

BAZPORS_ONLY_MIRROR_ACTS: frozenset[str] = frozenset(
    {
        "ysp",
        "ysc",
        "ysb",
        "ycp",
        "ycc",
        "ycb",
        "nii1",
        "nii1s",
        "nii2",
        "nii2a",
        "nii2r",
        "niisk",
        "ihok",
        "ihco",
        "ihdi",
        "sgt",
        "sgc",
        "sgb",
        "chs",
    }
)

MOZAKERE_ONLY_MIRROR_ACTS: frozenset[str] = frozenset(
    {"negp", "negc", "negb", "jic", "jrp", "jrc", "jrb"}
)

DEFENSE_MIRROR_ACTS: frozenset[str] = frozenset(
    {
        "d1dc",
        "d1dn",
        "d1d0",
        "d1d1",
        "d1el",
        "d1ey",
        "d1en",
        "elim_yes",
        "elim_no",
        "d1dt",
        "d1dt-60",
        "d1_skip",
        "d1_vote",
        "pea",
    }
)

STRUCTURED_CALLBACK_CLASSES = (
    JoinConfirmCb,
    CreatePickScenario,
    CreatePickPlayers,
    CreatePickHostMode,
    SemiAutoDevLobby,
    NoHostObserverPrompt,
    NoHostBotAssistantPick,
    NoHostIntroNightStart,
    NoHostDay1DefenseCb,
    HostPanel,
    PlayerEndApprove,
    PlayerEndDismiss,
    PlayerEndBroadcastConfirm,
    HubMenu,
    AmirHostDoc,
    MedalPick,
    BazporsNarrCb,
    ChaosHandshakeCb,
    EndGamePick,
    EndGameDismiss,
    EndGameAbortConfirm,
    RateHostStars,
    RateHostSkip,
    PlayerMirrorCb,
)


def _p(uid: int, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        is_alive=True,
    )


def _bazpors_no_host_game():
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.phase = Phase.NIGHT
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 999
    gm.add_player(game, _p(10, Role.MAFIA_BOSS))
    gm.add_player(game, _p(20, Role.DETECTIVE))
    return game


def _mozakere_no_host_game():
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.phase = Phase.NIGHT
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 999
    gm.add_player(game, _p(10, Role.MAFIA_BOSS))
    gm.add_player(game, _p(11, Role.MAFIA_NEGOTIATOR))
    gm.add_player(game, _p(40, Role.JOURNALIST))
    return game


def _prime_game_for_mirror_act(game, act: str) -> None:
    if act in ("ihok", "ihco", "ihdi"):
        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
    if act == "chs":
        game.bazpors_narrator_step = CHAOS_DAY_HANDSHAKE


def mirror_act_is_handled(game, act: str) -> bool:
    _prime_game_for_mirror_act(game, act)
    checks = (
        chaos_handshake_mirror_act_active,
        mafia_night1_act_active,
        mafia_shot_act_active,
        mafia_yaku_act_active,
        mafia_nato_act_active,
        mozakere_negotiator_act_active,
        hunter_night1_act_active,
        no_host_shiad_act_active,
        no_host_detective_act_active,
        no_host_doctor_act_active,
        no_host_interrog_day_act_active,
        no_host_interrog_act_active,
        no_host_sniper_act_active,
        no_host_journalist_act_active,
        no_host_ruintan_act_active,
        no_host_night_wait_ok_act_active,
        no_host_citizen_act_active,
    )
    if any(fn(game, act) for fn in checks):
        return True
    if act in DEFENSE_MIRROR_ACTS or act.startswith("d1dt"):
        return True
    return False


class CallbackButtonRoutingTests(unittest.TestCase):
    def test_structured_callback_prefixes_are_registered(self) -> None:
        prefixes = {cls.__prefix__ for cls in STRUCTURED_CALLBACK_CLASSES}
        self.assertIn("pmr", prefixes)
        self.assertIn("bzn", prefixes)
        self.assertIn("crs", prefixes)
        self.assertIn("egw", prefixes)
        self.assertGreaterEqual(len(prefixes), 15)

    def test_bazpors_mirror_acts_have_handler(self) -> None:
        game = _bazpors_no_host_game()
        for act in sorted(NO_HOST_MIRROR_ACTS - MOZAKERE_ONLY_MIRROR_ACTS):
            self.assertTrue(
                mirror_act_is_handled(game, act),
                f"Unhandled pmr act for Bazpors: {act}",
            )

    def test_mozakere_mirror_acts_have_handler(self) -> None:
        game = _mozakere_no_host_game()
        for act in sorted(NO_HOST_MIRROR_ACTS - BAZPORS_ONLY_MIRROR_ACTS):
            self.assertTrue(
                mirror_act_is_handled(game, act),
                f"Unhandled pmr act for Mozakere: {act}",
            )

    def test_mozakere_negotiation_acts_active_only_in_mozakere(self) -> None:
        self.assertTrue(mozakere_negotiator_act_active(_mozakere_no_host_game(), "negc"))
        self.assertFalse(mozakere_negotiator_act_active(_bazpors_no_host_game(), "negc"))

    def test_journalist_acts_active_only_in_mozakere(self) -> None:
        self.assertTrue(no_host_journalist_act_active(_mozakere_no_host_game(), "jic"))
        self.assertFalse(no_host_journalist_act_active(_bazpors_no_host_game(), "jic"))

    def test_player_mirror_callback_packs(self) -> None:
        packed = PlayerMirrorCb(code="R1", act="negc", as_uid=11, tid=60).pack()
        self.assertTrue(packed.startswith("pmr:"))
