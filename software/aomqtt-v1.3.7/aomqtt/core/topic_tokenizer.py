from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from .config import AOMQTTConfig
from ..exceptions import AOMQTTConfigurationError


def _normalize_topic(topic: str) -> str:
    topic = topic.strip()
    if not topic:
        raise AOMQTTConfigurationError("topic must not be empty")
    if "#" in topic or "+" in topic:
        raise AOMQTTConfigurationError(
            "publish topic must not contain MQTT wildcards. "
            "For subscribe wildcard support, use tokenize_filter()."
        )
    if topic.startswith("/") or topic.endswith("/") or "//" in topic:
        raise AOMQTTConfigurationError(
            "this prototype expects relative topics without empty levels"
        )
    return topic


class TopicTokenizer:
    """HMAC-SHA256 based topic tokenization.

    v0.2 supports two explicit modes:

    1. whole mode
       original:      shelter/siteA/starlink/rtt
       tokenized:     aomqtt/v1/t/<HMAC(topic)>
       property:      hides the number of topic levels, but cannot represent
                      MQTT wildcards without a separate topic directory.

    2. hierarchical mode
       original:      shelter/siteA/starlink/rtt
       tokenized:     aomqtt/v1/h/<HMAC(shelter)>/<HMAC(siteA)>/...
       property:      preserves the MQTT hierarchy and supports limited
                      wildcard subscription over tokenized filters.

    Optional epoch is reserved for future token rotation:
      HMAC(topic || epoch) or HMAC(level || epoch)
    """

    def __init__(self, config: AOMQTTConfig):
        config.validate()
        self.config = config
        self._key = config.topic_key.encode("utf-8")

    def _digest(self, value: str, *, context: str, epoch: Optional[str] = None) -> str:
        msg = f"{context}\x1f{value}"
        if epoch is not None:
            msg += f"\x1fepoch={epoch}"
        return hmac.new(self._key, msg.encode("utf-8"), hashlib.sha256).hexdigest()[: self.config.token_hex_len]

    def tokenize(self, topic: str, *, epoch: Optional[str] = None) -> str:
        topic = _normalize_topic(topic)
        if self.config.token_mode == "whole":
            return self.tokenize_whole(topic, epoch=epoch)
        return self.tokenize_hierarchical(topic, epoch=epoch)

    def tokenize_whole(self, topic: str, *, epoch: Optional[str] = None) -> str:
        topic = _normalize_topic(topic)
        token = self._digest(topic, context="topic", epoch=epoch)
        return f"{self.config.topic_prefix}/t/{token}"

    def tokenize_hierarchical(self, topic: str, *, epoch: Optional[str] = None) -> str:
        topic = _normalize_topic(topic)
        levels = topic.split("/")
        tokens = [self._digest(level, context="level", epoch=epoch) for level in levels]
        return f"{self.config.topic_prefix}/h/" + "/".join(tokens)

    def tokenize_filter(self, topic_filter: str, *, epoch: Optional[str] = None) -> str:
        """Tokenize a subscribe filter.

        In hierarchical mode, MQTT wildcards + and # are preserved at the same
        level. This enables limited wildcard subscriptions over tokenized topics.

        In whole mode, wildcards cannot be represented without a topic directory,
        so wildcard filters are rejected.
        """
        topic_filter = topic_filter.strip()
        if not topic_filter:
            raise AOMQTTConfigurationError("topic_filter must not be empty")
        if topic_filter.startswith("/") or topic_filter.endswith("/") or "//" in topic_filter:
            raise AOMQTTConfigurationError("this prototype expects relative filters without empty levels")

        if self.config.token_mode == "whole":
            if "+" in topic_filter or "#" in topic_filter:
                raise AOMQTTConfigurationError(
                    "wildcard subscribe is not supported in whole-topic token mode"
                )
            return self.tokenize(topic_filter, epoch=epoch)

        out = []
        levels = topic_filter.split("/")
        for i, level in enumerate(levels):
            if level == "+":
                out.append("+")
            elif level == "#":
                if i != len(levels) - 1:
                    raise AOMQTTConfigurationError("# wildcard must be the last level")
                out.append("#")
            elif "+" in level or "#" in level:
                raise AOMQTTConfigurationError("wildcards must occupy an entire topic level")
            else:
                out.append(self._digest(level, context="level", epoch=epoch))
        return f"{self.config.topic_prefix}/h/" + "/".join(out)

    def compare_modes(self, topic: str, *, epoch: Optional[str] = None) -> dict[str, str]:
        """Return both token forms for explanation, tests, and demonstrations."""
        topic = _normalize_topic(topic)
        return {
            "hierarchical": self.tokenize_hierarchical(topic, epoch=epoch),
            "whole": self.tokenize_whole(topic, epoch=epoch),
        }
