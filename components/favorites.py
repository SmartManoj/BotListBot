import datetime
import re
import threading

from telegram import ReplyMarkup
from telegram.ext import ConversationHandler

import captions
import const
import mdformat
import messages
import util
from const import CallbackActions, DeepLinkingActions
from model import Bot
from model import User
from model.favorite import Favorite
from telegram import ForceReply
from telegram import InlineKeyboardButton
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup


def add_favorite_handler(bot, update, args=None):
    uid = util.uid_from_update(update)
    from bot import _main_menu_buttons
    main_menu_markup = ReplyKeyboardMarkup(_main_menu_buttons(uid in const.MODERATORS))

    if args:
        query = ' '.join(args) if isinstance(args, list) else args
        try:
            # TODO: add multiple
            username = re.match(const.REGEX_BOT_IN_TEXT, query).groups()[0]
            try:
                # TODO: get exact database matches for input without `@`
                item = Bot.by_username(username)

                return add_favorite(bot, update, item)
            except Bot.DoesNotExist:
                buttons = [
                    InlineKeyboardButton(
                        "Yai!", callback_data=util.callback_for_action(CallbackActions.ADD_ANYWAY, {'u': username})),
                    InlineKeyboardButton("Nay...", callback_data=util.callback_for_action(CallbackActions.ADD_FAVORITE))
                ]
                reply_markup = InlineKeyboardMarkup([buttons])
                util.send_md_message(bot, uid,
                                     "{} is not in the @BotList. Do you want to add it to your {} anyway?".format(
                                         username, captions.FAVORITES),
                                     reply_markup=reply_markup)
        except AttributeError:
            # invalid bot username
            # TODO when does this happen?
            update.message.reply_text(
                util.failure("Sorry, but that is not a valid username. Please try again. /addfav"))
    else:
        buttons = [
            InlineKeyboardButton("Search inline", switch_inline_query_current_chat='')
        ]
        reply_markup = InlineKeyboardMarkup([buttons])

        bot.sendMessage(uid, messages.ADD_FAVORITE, reply_markup=ForceReply(selective=True))
    return ConversationHandler.END


def add_favorite(bot, update, item: Bot, callback_alert=None):
    user = User.from_update(update)
    uid = util.uid_from_update(update)
    mid = util.mid_from_update(update)
    from bot import _main_menu_buttons
    main_menu_markup = ReplyKeyboardMarkup(_main_menu_buttons(uid in const.MODERATORS))

    fav, created = Favorite.add(user=user, item=item)
    if created:
        text = mdformat.love("{} added to your {}favorites.".format(fav.bot, '' if callback_alert else '/'))
        if callback_alert:
            update.callback_query.answer(text=text, show_alert=False)
        else:
            msg = util.send_or_edit_md_message(bot, uid, text, to_edit=mid, reply_markup=main_menu_markup)
            mid = msg.message_id
            util.wait(bot, update)
            send_favorites_list(bot, update, to_edit=mid)
    else:
        text = mdformat.none_action(
            "{} is already a favorite of yours.{}".format(fav.bot, '' if callback_alert else ' /favorites'))
        if callback_alert:
            update.callback_query.answer(text=text, show_alert=False)
        else:
            util.send_md_message(bot, uid, text, reply_markup=main_menu_markup)
    return ConversationHandler.END


def send_favorites_list(bot, update, to_edit=None):
    uid = util.uid_from_update(update)
    user = User.from_update(update)

    t = threading.Thread(target=_too_many_favorites_handler, args=(bot, update, user))
    t.start()

    favorites = Favorite.select_all(user)

    text = None
    if len(favorites) == 0:
        text = "You have no favorites yet."

    buttons = [
        [
            InlineKeyboardButton(captions.ADD_FAVORITE,
                                 callback_data=util.callback_for_action(CallbackActions.ADD_FAVORITE)),
            InlineKeyboardButton(captions.REMOVE_FAVORITE,
                                 callback_data=util.callback_for_action(CallbackActions.REMOVE_FAVORITE_MENU))
        ],
        [
            InlineKeyboardButton(captions.SHARE, switch_inline_query=DeepLinkingActions.FAVORITES),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    if to_edit is None:
        to_edit = util.mid_from_update(update)
    if text is None:
        text = _favorites_categories_md(favorites)
    util.send_or_edit_md_message(bot, uid, text,
                                 to_edit=to_edit, reply_markup=reply_markup)


def _favorites_categories_md(favorites):
    # sort favorites by database order
    favorites.sort(key=lambda x: x.bot.category.order)

    chunks = list()
    current_category = None
    for n, f in enumerate(favorites):
        bot = f.bot
        category = bot.category

        try:
            if favorites[n + 1].bot.category != category:
                list_icon = '└'
            else:
                list_icon = '├'
        except IndexError:
            list_icon = '└'

        if current_category is None or category != current_category:
            category_no_bulletin = str(category)[1:]
            chunks.append('\n*{}*'.format(category_no_bulletin))

        chunks.append('{} {}'.format(list_icon, str(bot)))
        current_category = category

    all_favorites = '\n'.join(chunks)
    text = messages.FAVORITES_HEADLINE + '\n' + all_favorites
    return text


def remove_favorite_menu(bot, update):
    uid = util.uid_from_update(update)
    user = User.from_update(update)
    favorites = Favorite.select_all(user)

    fav_remove_buttons = [InlineKeyboardButton(
        '✖️ {}'.format(str(f.bot.username)),
        callback_data=util.callback_for_action(CallbackActions.REMOVE_FAVORITE, {'id': f.id}))
                          for f in favorites]
    buttons = util.build_menu(fav_remove_buttons, 2, header_buttons=[
        InlineKeyboardButton(captions.DONE,
                             callback_data=util.callback_for_action(CallbackActions.SEND_FAVORITES_LIST))
    ])
    reply_markup = InlineKeyboardMarkup(buttons)
    util.send_or_edit_md_message(bot, uid, util.action_hint("Select favorites to remove"),
                                 to_edit=util.mid_from_update(update),
                                 reply_markup=reply_markup)


def _too_many_favorites_handler(bot, update, user):
    uid = util.uid_from_update(update)
    while too_many_favorites(user):
        oldest = Favorite.get_oldest(user)
        print(oldest.bot)
        txt = "You have too many favorites, _they do not fit into a single message_. That's why I removed your " \
              "oldest bot, *{}*, from your list of favorites.".format(oldest.bot if oldest.bot else oldest.custom_bot)
        oldest.delete_instance()
        util.send_md_message(bot, uid, txt)


def too_many_favorites(user):
    favs = Favorite.select_all(user)
    promo = max(len(messages.PROMOTION_MESSAGE), len(messages.FAVORITES_HEADLINE))
    message_length = len(_favorites_categories_md(favs)) + promo + 4
    return message_length > 4096


def add_custom(bot, update, username):
    uid = util.uid_from_update(update)
    user = User.from_update(update)
    mid = util.mid_from_update(update)
    from bot import _main_menu_buttons
    main_menu_markup = ReplyKeyboardMarkup(_main_menu_buttons(uid in const.MODERATORS))

    try:
        fav = Favorite.get(custom_bot=username)
        util.send_or_edit_md_message(
            bot, uid, mdformat.none_action(
                "{} is already a favorite of yours. /favorites".format(fav.custom_bot)),
            to_edit=mid,
            reply_markup=main_menu_markup)
    except Favorite.DoesNotExist:
        fav = Favorite(user=user, custom_bot=username, date_added=datetime.date.today())
        fav.save()
        msg = util.send_or_edit_md_message(bot, uid,
                                           mdformat.love("{} added to your /favorites.".format(fav.custom_bot)),
                                           to_edit=mid)
        mid = msg.message_id
        util.wait(bot, update)
        send_favorites_list(bot, update, to_edit=mid)
    return ConversationHandler.END
