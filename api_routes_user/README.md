# api_routes_user · 本机路由叠层

官方升级不碰这里。模块 export router = APIRouter() 即挂上。
不要占用 /dashboard/{任意}，那条会被官方通配吞掉。用 /mod/<你的id>/…
