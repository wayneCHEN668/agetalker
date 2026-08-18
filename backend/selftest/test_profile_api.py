"""「我自己」那一页背后的读写接口。

这一页是给**老人自己**看、自己改的，所以只列 13 个 askable 字段：
external（紧急联系人/药名/房间号）是护理员录的，observable（话多话少/情绪底色）
是系统从行为统计出来的、手改下一轮就被盖掉。

两个容易被忽略的点，都在下面锁住了：

1. **要能清空。** 实盘画像里 address 的值是「我」——从 AI 自己那句
   「我该怎么称呼你呀？」里抽错的。一个改不掉错值的编辑页没有意义。
   清空后回 unknown，AI 以后会重新问。
2. **岁数要收得住。** schema 只存四位年份（存年龄一年后就是错的，
   见 set_birth_year 的 docstring），但这一栏对老人显示的是「岁数」，
   他一定会输 83。转换放在写入口，schema 不动。
"""
import pytest

from services.profile_schema import ASKABLE_SLOTS, EXTERNAL_SLOTS, OBSERVABLE_SLOTS
from services.profile_service import (
    ProfileService, STATUS_FILLED, STATUS_UNKNOWN, compute_age,
)


@pytest.fixture
def svc(tmp_path):
    return ProfileService(storage_dir=str(tmp_path))


ELDER = 'elder_test'


# ─── 列出来的是哪些字段 ──────────────────────────────────────────────────────

def test_lists_only_askable_slots(svc):
    names = [row['name'] for row in svc.list_editable_slots(ELDER)]
    assert names and set(names) == set(ASKABLE_SLOTS)
    for hidden in EXTERNAL_SLOTS + OBSERVABLE_SLOTS:
        assert hidden not in names


def test_rows_are_ordered_by_priority(svc):
    """称呼排第一——它每句话都用得上，也是定时招呼的前置。"""
    rows = svc.list_editable_slots(ELDER)
    assert rows[0]['name'] == 'address'
    assert rows[1]['name'] == 'sensory_hearing'


def test_rows_carry_the_chinese_label(svc):
    """页面上不能出现英文字段名。"""
    rows = {r['name']: r for r in svc.list_editable_slots(ELDER)}
    assert rows['address']['zh'] == '称呼'
    assert rows['hometown']['zh'] == '老家'


def test_untouched_slots_come_back_empty(svc):
    """还没采到的保持为空——页面据此显示灰色的「还没说」。"""
    rows = {r['name']: r for r in svc.list_editable_slots(ELDER)}
    assert rows['hometown']['value'] == ''
    assert rows['hometown']['status'] == STATUS_UNKNOWN


# ─── 手工写入 ────────────────────────────────────────────────────────────────

def test_manual_edit_fills_the_slot(svc):
    assert svc.set_slot_manually(ELDER, 'hometown', '河北保定') is True
    slot = svc.get_profile(ELDER)['slots']['hometown']
    assert slot['value']  == '河北保定'
    assert slot['status'] == STATUS_FILLED
    assert slot['source'] == 'manual'


def test_manual_edit_survives_a_reload(svc, tmp_path):
    """改完必须落盘——不然重启就没了。"""
    svc.set_slot_manually(ELDER, 'hometown', '河北保定')
    fresh = ProfileService(storage_dir=str(tmp_path))
    assert fresh.get_profile(ELDER)['slots']['hometown']['value'] == '河北保定'


def test_manual_edit_overrides_a_wrong_extracted_value(svc):
    """实盘那条 address = 「我」正是这个场景。"""
    svc.set_slot_manually(ELDER, 'address', '我')
    svc.set_slot_manually(ELDER, 'address', '王爷爷')
    assert svc.get_profile(ELDER)['slots']['address']['value'] == '王爷爷'


def test_unknown_slot_name_is_rejected(svc):
    assert svc.set_slot_manually(ELDER, 'not_a_slot', '随便') is False


def test_non_askable_slots_are_not_editable_here(svc):
    """这一页只管 askable。紧急联系人不该能从老人的界面写进去。"""
    assert svc.set_slot_manually(ELDER, 'emergency_contact', '儿子 13800138000') is False
    assert svc.set_slot_manually(ELDER, 'talkativeness', '话很多') is False


# ─── 清空 ────────────────────────────────────────────────────────────────────

def test_clearing_resets_the_slot_to_unknown(svc):
    """清了就该回到「没采过」，AI 以后会重新问。"""
    svc.set_slot_manually(ELDER, 'hometown', '河北保定')
    assert svc.set_slot_manually(ELDER, 'hometown', '') is True
    slot = svc.get_profile(ELDER)['slots']['hometown']
    assert slot['value']  == ''
    assert slot['status'] == STATUS_UNKNOWN


def test_clearing_also_drops_the_stale_evidence(svc):
    """留着旧 evidence 会让下一次抽取拿它当依据，等于没清干净。"""
    svc.set_slot_manually(ELDER, 'hometown', '河北保定')
    svc.set_slot_manually(ELDER, 'hometown', '   ')
    slot = svc.get_profile(ELDER)['slots']['hometown']
    assert slot['status']   == STATUS_UNKNOWN
    assert slot['evidence'] == ''
    assert slot['source']   == ''


# ─── 岁数：两种输入都收，都存成四位年份 ──────────────────────────────────────

def test_birth_year_accepts_a_four_digit_year(svc):
    assert svc.set_slot_manually(ELDER, 'birth_year', '1943') is True
    assert svc.get_profile(ELDER)['slots']['birth_year']['value'] == '1943'


def test_birth_year_accepts_an_age_and_converts_it(svc):
    """标签写着「岁数」，老人就会输 83。存进去的必须还是年份。"""
    assert svc.set_slot_manually(ELDER, 'birth_year', '83') is True
    assert compute_age(svc.get_profile(ELDER)) == 83


def test_birth_year_rejects_nonsense(svc):
    for bad in ('5', '999', '3000', '前年'):
        assert svc.set_slot_manually(ELDER, 'birth_year', bad) is False
    assert svc.get_profile(ELDER)['slots']['birth_year']['value'] == ''
