import re

from peewee import fn

import const
import settings
from model import Bot
from model import Category
from model import Keyword


def search_bots(query):
    # easter egg
    if query.lower() == 'awesome bot':
        return [Bot.by_username('@botlistbot')]

    query = query.lower().strip()
    split = query.split(' ')

    # exact results
    where_query = (
        (fn.lower(Bot.username).contains(query)) |
        (fn.lower(Bot.name) << split) |
        (fn.lower(Bot.extra) ** query)
    )
    results = set(Bot.select().distinct().where(where_query))

    # keyword results
    keyword_results = Bot.select(Bot).join(Keyword).where(fn.lower(Keyword.name) << split)
    results.update(keyword_results)

    # many @usernames
    usernames = re.findall(settings.REGEX_BOT_ONLY, query)
    if usernames:
        try:
            bots = Bot.many_by_usernames(usernames)
            results.update(bots)
        except Bot.DoesNotExist:
            pass

    return list(results)


def search_categories(query):
    query = query.lower().strip()
    categories = Category.select().where(
        (fn.lower(Category.name).contains(query)) |
        (fn.lower(Category.extra).contains(query))
    )
    return categories
