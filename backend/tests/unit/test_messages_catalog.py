from string import Formatter

from app.core.i18n.locales import SUPPORTED, DEFAULT
from app.core.i18n.messages import Keys, load_catalogs


def test_keys_is_str_enum():
    assert issubclass(Keys, str)
    # Spot check a representative sample.
    assert Keys.HTTP_TEMPLATE_NOT_FOUND == "http.template.not_found"
    assert Keys.SESSION_CONCURRENT_LIMIT == "session.concurrent_limit"


def test_supported_and_default():
    assert DEFAULT == "zh-CN"
    assert SUPPORTED == frozenset({"zh-CN", "zh-TW", "en-US", "vi-VN"})


def test_catalogs_load_for_every_supported():
    catalogs = load_catalogs()
    assert set(catalogs) == SUPPORTED


def test_every_key_has_en_us_translation():
    catalogs = load_catalogs()
    en_us = catalogs["en-US"]
    missing = [k.value for k in Keys if k.value not in en_us]
    assert missing == [], f"en-US missing: {missing}"


def test_every_translation_is_non_empty_string():
    catalogs = load_catalogs()
    for locale, entries in catalogs.items():
        for key, value in entries.items():
            assert isinstance(value, str) and value.strip(), \
                f"{locale}/{key} empty"


def test_catalog_keys_are_subset_of_keys_enum():
    """Reverse direction (catalog ⊆ Keys): every key in any catalog must
    correspond to a Keys member. Catches "orphan" catalog strings (e.g. someone
    adds `ws.foo.bar` to en_US.json without a matching `Keys.WS_FOO_BAR`)
    which would otherwise be unreachable via the enum and silently rot.
    """
    catalogs = load_catalogs()
    keys_set = {k.value for k in Keys}
    orphans = []
    for locale, entries in catalogs.items():
        for k in entries:
            if k not in keys_set:
                orphans.append(f"{locale}/{k}")
    assert orphans == [], f"orphan catalog keys not in Keys enum: {sorted(orphans)}"


def test_all_locales_have_same_keys():
    """zh-CN, zh-TW, en-US must expose identical key sets. Catches missing
    translations before runtime (rather than discovering them via fallback at
    the worst possible moment)."""
    catalogs = load_catalogs()
    sets = [{k for k in entries} for entries in catalogs.values()]
    reference = sets[0]
    for i, s in enumerate(sets[1:], start=1):
        assert s == reference, (
            f"catalog[{i}] differs from catalog[0]: "
            f"only_in_first={reference - s}, only_in_this={s - reference}"
        )


def test_every_catalog_entry_parses_with_string_formatter():
    """`t(key, **params)` runs `msg.format(**params)`. Two consequences:

    1. Every `{name}` placeholder must be a valid Python identifier, and any
       `{}` / `{0}` numeric placeholder must reference an auto-numbered field.
       This catches malformed strings like `'{min length}'` (space) or
       `'{0}'` with a positional placeholder that conflicts with kwargs.

    2. Two locales describing the same key must declare the same placeholder
       set; otherwise a caller passing `min_length=4` succeeds in zh-CN but
       crashes in en-US (or vice versa) because one string embeds the field
       and the other omits it.

    The first failure mode is fast and easy to fix; the second has bitten
    real teams when translators silently drop or rename a field.
    """
    catalogs = load_catalogs()
    formatter = Formatter()

    # Per-locale placeholder sanity.
    for locale, entries in catalogs.items():
        for key, value in entries.items():
            try:
                formatter.parse(value)
            except ValueError as e:
                pytest.fail(f"{locale}/{key} malformed format string: {e!r}")

    # Cross-locale placeholder parity. Group by key, compare placeholder sets
    # across every locale that ships a translation.
    by_key: dict[str, dict[str, set[str]]] = {}
    for locale, entries in catalogs.items():
        for key, value in entries.items():
            placeholders = {
                fname
                for _, fname, _, _ in formatter.parse(value)
                if fname
            }
            by_key.setdefault(key, {})[locale] = placeholders

    for key, per_locale in by_key.items():
        locales = list(per_locale.keys())
        reference_locale = locales[0]
        reference = per_locale[reference_locale]
        for locale in locales[1:]:
            assert per_locale[locale] == reference, (
                f"{key}: placeholders diverge between "
                f"{reference_locale}={sorted(reference)} and "
                f"{locale}={sorted(per_locale[locale])}"
            )