# ============================================================================
#  site-monitor —— Umami + Google Search Console 的站点监控服务
# ============================================================================
import warnings

# authlib / starlette 在过渡到 httpx2，httpx 仍可用；在上游迁移完成前屏蔽这条提示
warnings.filterwarnings("ignore", message=".*httpx2.*")
