"""
数据库工具函数
"""
import atexit
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)


def fix_db_uri_encoding(db_uri: str) -> str:
    """
    修复数据库 URI 中的特殊字符编码问题
    特别是处理密码中包含 @ 符号的情况
    
    Args:
        db_uri: 原始数据库 URI
        
    Returns:
        修复后的数据库 URI
        
    Examples:
        >>> fix_db_uri_encoding("postgresql://user:pass@word@localhost:5432/db")
        'postgresql://user:pass%40word@localhost:5432/db'
        
        >>> fix_db_uri_encoding("mysql://user:pass+word@localhost:3306/db")
        'mysql://user:pass%2Bword@localhost:3306/db'
    """
    try:
        # 使用更精确的正则表达式来解析数据库 URI
        # 格式: scheme://username:password@host:port/database
        import re
        
        # 匹配数据库 URI 的正则表达式
        # 使用非贪婪匹配来正确处理密码中的 @ 符号
        pattern = r'^([^:]+)://([^:]+):(.+)@([^:]+):(\d+)/(.+)$'
        match = re.match(pattern, db_uri)
        
        if match:
            scheme, username, password, host, port, database = match.groups()
            
            # 对用户名和密码进行 URL 编码
            encoded_username = quote_plus(username)
            encoded_password = quote_plus(password)
            
            # 重建 URI
            fixed_uri = f"{scheme}://{encoded_username}:{encoded_password}@{host}:{port}/{database}"
            return fixed_uri
        else:
            # 如果没有匹配到标准格式，尝试其他格式
            # 处理没有端口号的情况
            pattern_no_port = r'^([^:]+)://([^:]+):(.+)@([^/]+)/(.+)$'
            match = re.match(pattern_no_port, db_uri)
            
            if match:
                scheme, username, password, host, database = match.groups()
                
                # 对用户名和密码进行 URL 编码
                encoded_username = quote_plus(username)
                encoded_password = quote_plus(password)
                
                # 重建 URI
                fixed_uri = f"{scheme}://{encoded_username}:{encoded_password}@{host}/{database}"
                return fixed_uri
            else:
                # 如果都不匹配，返回原始 URI
                return db_uri
                
    except Exception:
        # 如果解析失败，返回原始 URI
        return db_uri


def is_clickhouse_uri(db_uri: str) -> bool:
    """
    检查是否为 ClickHouse/MyScale 数据库 URI

    Args:
        db_uri: 数据库 URI

    Returns:
        bool: 是否为 ClickHouse URI
    """
    return db_uri.startswith(('clickhouse://', 'clickhouse+connect://', 'myscale://', 'myscale+connect://'))


def is_vertica_uri(db_uri: str) -> bool:
    """
    检查是否为 Vertica 数据库 URI

    Args:
        db_uri: 数据库 URI

    Returns:
        bool: 是否为 Vertica URI
    """
    return db_uri.startswith('vertica://')


def parse_clickhouse_uri(db_uri: str) -> dict:
    """
    解析 ClickHouse/MyScale 连接字符串

    Args:
        db_uri: ClickHouse/MyScale URI，格式如:
                clickhouse://user:password@host:port/database
                clickhouse+connect://user:password@host:port/database
                myscale://user:password@host:port/database
                myscale+connect://user:password@host:port/database

    Returns:
        dict: 包含连接参数的字典
    """
    try:
        # 移除协议前缀
        if db_uri.startswith('clickhouse+connect://'):
            db_uri = db_uri.replace('clickhouse+connect://', '')
        elif db_uri.startswith('clickhouse://'):
            db_uri = db_uri.replace('clickhouse://', '')
        elif db_uri.startswith('myscale+connect://'):
            db_uri = db_uri.replace('myscale+connect://', '')
        elif db_uri.startswith('myscale://'):
            db_uri = db_uri.replace('myscale://', '')

        # 解析用户名、密码、主机、端口、数据库
        if '@' in db_uri:
            auth_part, host_part = db_uri.split('@', 1)

            # 解析用户名和密码
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
            else:
                username, password = auth_part, ''

            # 解析主机、端口和数据库
            if '/' in host_part:
                host_db_part = host_part.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else 'default'
            else:
                host_port = host_part
                database = 'default'

            # 解析主机和端口
            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 8123  # ClickHouse 默认端口

            return {
                'host': host,
                'port': int(port),
                'username': username,
                'password': password,
                'database': database
            }
        else:
            # 没有认证信息的情况
            if '/' in db_uri:
                host_db_part = db_uri.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else 'default'
            else:
                host_port = db_uri
                database = 'default'

            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 8123

            return {
                'host': host,
                'port': int(port),
                'username': 'default',
                'password': '',
                'database': database
            }
    except Exception:
        # 解析失败时返回默认配置
        return {
            'host': 'localhost',
            'port': 8123,
            'username': 'default',
            'password': '',
            'database': 'default'
        }

def parse_vertica_uri(db_uri: str) -> dict:
    """
    解析 Vertica 连接字符串

    Args:
        db_uri: Vertica URI，格式如:
                vertica://user:password@host:port/database

    Returns:
        dict: 包含连接参数的字典
    """
    try:
        if db_uri.startswith('vertica://'):
            db_uri = db_uri.replace('vertica://', '')

        if '@' in db_uri:
            auth_part, host_part = db_uri.split('@', 1)

            if ':' in auth_part:
                user, password = auth_part.split(':', 1)
            else:
                user, password = auth_part, ''

            if '/' in host_part:
                host_db_part = host_part.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else ''
            else:
                host_port = host_part
                database = ''

            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 5433

            return {
                'host': host,
                'port': int(port),
                'user': user,
                'password': password,
                'database': database,
                'autocommit': True,
            }
        else:
            if '/' in db_uri:
                host_db_part = db_uri.split('/', 1)
                host_port = host_db_part[0]
                database = host_db_part[1] if len(host_db_part) > 1 else ''
            else:
                host_port = db_uri
                database = ''

            if ':' in host_port:
                host, port = host_port.split(':', 1)
            else:
                host = host_port
                port = 5433

            return {
                'host': host,
                'port': int(port),
                'user': '',
                'password': '',
                'database': database,
                'autocommit': True,
            }
    except Exception:
        return {
            'host': 'localhost',
            'port': 5433,
            'user': 'dbadmin',
            'password': '',
            'database': '',
            'autocommit': True,
        }


def parse_config_options(raw) -> dict:
    """
    解析 config_options 参数（JSON 字符典或字典），返回字典。

    解析失败时抛出 ValueError("Invalid JSON format for Connect Config")，
    与原有工具的错误信息保持一致。
    """
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        options = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format for Connect Config")
    if not isinstance(options, dict):
        raise ValueError("Invalid JSON format for Connect Config")
    return options


_DEFAULT_IDLE_TTL = 600.0
_DEFAULT_MAX_ENGINES = 16
_SWEEP_INTERVAL = 60.0

_DEFAULT_POOL_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "pool_size": 5,
    "max_overflow": 5,
    "pool_timeout": 30,
}


def _engine_kwargs(db_uri: str, options: dict) -> dict:
    kwargs = dict(_DEFAULT_POOL_OPTIONS)
    scheme = db_uri.split(":", 1)[0].lower()
    is_sqlite = scheme.startswith("sqlite")
    memory_sqlite = is_sqlite and (":memory:" in db_uri or db_uri in ("sqlite://", "sqlite:///:memory:"))
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    if memory_sqlite:
        kwargs["poolclass"] = StaticPool
    user_options = dict(options)
    if is_sqlite and isinstance(user_options.get("connect_args"), dict):
        kwargs["connect_args"] = {**kwargs["connect_args"], **user_options.pop("connect_args")}
    kwargs.update(user_options)
    if memory_sqlite:
        for queue_only in ("pool_size", "max_overflow", "pool_timeout"):
            kwargs.pop(queue_only, None)
    return kwargs


class EngineRegistry:
    """
    进程级 SQLAlchemy engine 注册表，用于修复连接泄漏问题。

    原版每次调用都新建 engine（含独立连接池），靠垃圾回收释放连接，
    导致 MySQL/PG 等会话堆积在 SLEEP 状态。此处：

    - 按 (URI + 选项) 缓存并复用 engine，调用结束后连接确定性归还连接池；
    - 空闲超过 TTL 的 engine 自动 dispose，后台线程定期清理；
    - LRU 上限限制同时存在的 engine 数量（即 socket 数量）；
    - pool_pre_ping / pool_recycle 对抗服务端超时断开的陈旧连接。
    """

    def __init__(self, max_engines: int = _DEFAULT_MAX_ENGINES, idle_ttl: float = _DEFAULT_IDLE_TTL):
        self._max_engines = max_engines
        self._idle_ttl = idle_ttl
        self._engines = OrderedDict()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._sweeper = None

    def _ensure_started_locked(self):
        # 线程延迟到第一次使用时启动：dify_plugin 导入时会 monkey-patch threading(gevent)，
        # 若在此之前启动真实线程会导致其导入挂起
        if self._sweeper is None:
            self._sweeper = threading.Thread(target=self._sweep_loop, name="database-engine-sweeper", daemon=True)
            self._sweeper.start()
            atexit.register(self.dispose_all)

    @staticmethod
    def _key(db_uri: str, options: dict) -> str:
        return db_uri + "|" + json.dumps(options, sort_keys=True, default=str)

    def get(self, db_uri: str, options: dict = None):
        options = options or {}
        key = self._key(db_uri, options)
        now = time.monotonic()
        with self._lock:
            self._ensure_started_locked()
            self._evict_expired_locked(now)
            entry = self._engines.get(key)
            if entry is not None:
                self._engines[key] = (entry[0], now)
                self._engines.move_to_end(key)
                return entry[0]
            engine = create_engine(db_uri, **_engine_kwargs(db_uri, options))
            self._engines[key] = (engine, now)
            while len(self._engines) > self._max_engines:
                _, (victim, _) = self._engines.popitem(last=False)
                victim.dispose()
            return engine

    def discard(self, db_uri: str, options: dict = None):
        key = self._key(db_uri, options or {})
        with self._lock:
            entry = self._engines.pop(key, None)
        if entry is not None:
            entry[0].dispose()

    def _evict_expired_locked(self, now: float):
        expired = [k for k, (_, used) in self._engines.items() if now - used > self._idle_ttl]
        for k in expired:
            engine, _ = self._engines.pop(k)
            engine.dispose()

    def _sweep_loop(self):
        while not self._stop.wait(_SWEEP_INTERVAL):
            try:
                with self._lock:
                    self._evict_expired_locked(time.monotonic())
            except Exception:
                logger.exception("database engine sweeper iteration failed")

    def dispose_all(self):
        with self._lock:
            engines = [e for e, _ in self._engines.values()]
            self._engines.clear()
        for engine in engines:
            engine.dispose()


REGISTRY = EngineRegistry()


def get_engine(db_uri: str, options: dict = None):
    return REGISTRY.get(db_uri, options)


def discard_engine(db_uri: str, options: dict = None):
    return REGISTRY.discard(db_uri, options)