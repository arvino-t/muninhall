from muninhall.litres import is_blocked


def test_trackers_are_blocked():
    assert is_blocked("static.a.mts.ru")
    assert is_blocked("mc.yandex.ru")
    assert is_blocked("www.googletagmanager.com")


def test_litres_and_sign_in_providers_are_not():
    for host in ("www.litres.ru", "api.litres.ru", "cdn.litres.ru", "id.vk.com", "oauth.yandex.ru",
                 "passport.yandex.ru", "id.sber.ru", "mts.ru", "notmc.yandex.ru"):
        assert not is_blocked(host), host
