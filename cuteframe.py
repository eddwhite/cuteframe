import os
from instaloader import Instaloader, Post
from telegram import Update, TelegramObject
from telegram.ext import ConversationHandler, filters, MessageHandler, CommandHandler, TypeHandler, ApplicationBuilder, ContextTypes, ApplicationHandlerStop
from mysecrets import BOT_TOKEN
import ffmpeg
from pyrlottie import LottieFile, convSingleLottie
from gpiozero import PWMLED


insta = Instaloader(filename_pattern='{shortcode}')

backlight = PWMLED(18, initial_value=0)


def resize_media(in_path: str, out_path: str) -> None:
    # Get the width and height
    probe = ffmpeg.probe(in_path)
    width, height = probe['streams'][0]['width'], probe['streams'][0]['height']
    print(f'Input file is {width}x{height}')

    stream = ffmpeg.input(in_path)

    # First upscale if necessary
    if width < 720 or height < 720:
        scale_factor = 720 / min(width, height)
        width = int(width * scale_factor)
        height = int(height * scale_factor)
        stream = stream.filter('scale', width, height)

    # Crop to the correct aspect ratio
    if width != 720 or height != 720:
        excess_height = height - 720
        excess_width = width - 720
        # Crop the video to the desired size
        stream = stream.crop(x=excess_width/2, y=excess_height/2, width=720, height=720)

    # Different output command for images
    if in_path.endswith(('.png', '.jpg', '.jpeg')):
        stream = stream.output(out_path, vframes=1)
    else:
        stream = stream.output(out_path)

    stream.run(overwrite_output=True)


async def download_media(obj: TelegramObject, context: ContextTypes.DEFAULT_TYPE) -> str:
    print(f'Downloading {obj}')
    file = await context.bot.get_file(obj)
    out_file_path = f'tmp/{file.file_id}.{file.file_path.split(".")[-1]}'
    await file.download_to_drive(out_file_path)
    return out_file_path


async def url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    insta_shortcode = update.message.text.split('/reel/')[1].split('/')[0]
    print(f"Got shortcode {insta_shortcode} from url: {update.message.text}")
    post = Post.from_shortcode(insta.context, insta_shortcode)
    insta.download_post(post, 'tmp/')
    resize_media(f'tmp/{insta_shortcode}.mp4', f'out/{insta_shortcode}.mp4')

async def sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out_file_path = await download_media(update.message.sticker, context)
    # Convert telegram sticker to gif
    out = (await convSingleLottie(lottieFile=LottieFile(out_file_path), destFiles={out_file_path.replace('.tgs', '.gif')})).pop()
    resize_media(out, f'out/{out_file_path.split("/")[-1].replace(".tgs", ".gif")}')

async def gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out_file_path = await download_media(update.message.animation, context)
    resize_media(out_file_path, f'out/{out_file_path.split("/")[-1]}')

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out_file_path = await download_media(update.message.photo[-1], context)
    resize_media(out_file_path, f'out/{out_file_path.split("/")[-1]}')


async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Got something unexpected: {update.message}")
    await context.bot.send_message(update.message.chat_id, "Sorry, I don't understand that command")


async def brightness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    print(f"Got brightness command with args: {context.args}")
    if len(context.args) > 0:
        try:
            backlight.value = 1 - (int(context.args[0]) / 100)
            return ConversationHandler.END
        except ValueError:
            pass
    await update.message.reply_text("Now send a number between 0 and 100")
    return 0

async def brightness_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        backlight.value = 1 - (int(update.message.text) / 100)
        return ConversationHandler.END
    except ValueError:
        pass
    await update.message.reply_text("Try again! Send a number between 0 and 100 (or /cancel to give up!)")
    return 0

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Try again another time!")
    return ConversationHandler.END

async def shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("Turning off!")
    os.system("sudo shutdown -h now")

async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("Rebooting!")
    os.system("sudo reboot")

async def restrict_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in [1158879753]:
        pass
    else:
        await update.effective_message.reply_text("Hey! You are not allowed to use me!")
        raise ApplicationHandlerStop

async def post_init(application) -> None:
    await application.bot.set_my_commands([('brightness', 'Set the brightness [0-100]'), ('shutdown', 'Shutdown safely'), ('reboot', 'Reboot')])

# Make directories if they don't exist
if not os.path.exists('out'):
    os.makedirs('out')
if not os.path.exists('tmp'):
    os.makedirs('tmp')

app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

app.add_handler(TypeHandler(Update, restrict_users), -1)

app.add_handler(ConversationHandler(entry_points=[CommandHandler('brightness', brightness)], states={0: [MessageHandler(filters.TEXT & ~filters.COMMAND, brightness_value)],}, fallbacks=[CommandHandler("cancel", cancel)]))
app.add_handler(CommandHandler('shutdown', shutdown))
app.add_handler(CommandHandler('reboot', reboot))
app.add_handler(MessageHandler(filters.PHOTO, photo))
app.add_handler(MessageHandler(filters.ANIMATION, gif))
app.add_handler(MessageHandler(filters.Sticker.ALL, sticker))
app.add_handler(MessageHandler(filters.TEXT & (filters.Entity("url") | filters.Entity("text_link")), url))
app.add_handler(MessageHandler(filters.ALL, catch_all))
app.run_polling()
