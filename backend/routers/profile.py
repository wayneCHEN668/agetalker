"""画像读写路由 —— 前端「我自己」那一页。

这一页是给老人自己看、自己改的，所以只暴露 askable 字段：
external（紧急联系人/药名/房间号）是护理员录的，observable（话多话少/情绪底色）
是系统从对话行为统计出来的。门槛在 ProfileService.set_slot_manually 里，
不在这一层——路由只做搬运。
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.profile_service import ProfileService

logger = logging.getLogger(__name__)
router = APIRouter()

# 服务实例由 main.py 注入。MEMORY_ENABLED=0 时是 None——画像和台账共用同一个
# 开关，关掉之后这一页应当明确地空着，而不是报错。
profile_service: ProfileService = None


class SlotUpdate(BaseModel):
    elder_id: str = Field(..., description="老人 ID（跨会话稳定）")
    name:     str = Field(..., description="字段名，必须是 askable 之一")
    value:    str = Field(default='', description="新值。空串表示清掉这个字段")


@router.get('/profile')
async def get_profile(elder_id: str = 'default_elder'):
    """「我自己」页要显示的那一列，按优先级排。没采到的 value 是空串。"""
    if profile_service is None:
        return {'slots': [], 'enabled': False}
    return {'slots': profile_service.list_editable_slots(elder_id), 'enabled': True}


@router.post('/profile/slot')
async def update_slot(req: SlotUpdate):
    """改一个字段。value 传空串就是清掉，清完 AI 以后会重新问。"""
    if profile_service is None:
        return {'ok': False, 'reason': 'profile_disabled'}

    ok = profile_service.set_slot_manually(req.elder_id, req.name, req.value)
    if not ok:
        # 字段名非法、不可手工编辑，或岁数填得不成样子
        return {'ok': False, 'reason': 'rejected'}

    logger.info(f"画像手工编辑: {req.elder_id} | {req.name} = {req.value or '（清空）'}")
    row = next(
        (r for r in profile_service.list_editable_slots(req.elder_id)
         if r['name'] == req.name),
        None,
    )
    return {'ok': True, 'slot': row}
