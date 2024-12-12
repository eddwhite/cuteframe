import os
from instaloader import Instaloader, Post
from telegram import Update, TelegramObject
from telegram.ext import ConversationHandler, filters, MessageHandler, CommandHandler, TypeHandler, ApplicationBuilder, ContextTypes, ApplicationHandlerStop
from mysecrets import BOT_TOKEN
import ffmpeg
import subprocess as sp
import glob
import requests
import json
import gzip
import time


os.chdir("/home/frame/cuteframe/")

insta = Instaloader(filename_pattern='{shortcode}')
player = sp.Popen("exec mpv --fs --loop out/default.mp4", shell=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
sp.run("gpio -g mode 18 pwm && gpio pwmc 100", shell=True)


def clear_tmp() -> None:
    files = glob.glob('tmp/*')
    for f in files:
        os.remove(f)

def update_display(file_path: str) -> None:
    global player
    player.kill()
    player.wait()
    player = sp.Popen(f"exec mpv --fs --loop {file_path}", shell=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    clear_tmp()

def resize_media(in_path: str, out_path: str) -> str:
    global player
    player.kill()  # Kill the player so we have some CPU for ffmpeg!

    if os.path.isfile(out_path):
        return out_path

    # Get the width and height
    probe = ffmpeg.probe(in_path)
    width, height = probe['streams'][0]['width'], probe['streams'][0]['height']
    print(f'Input file is {width}x{height}')

    stream = ffmpeg.input(in_path).video

    # Crop to the correct aspect ratio
    smallest_side = min(width, height)
    if width != height:
        excess_height = height - smallest_side
        excess_width = width - smallest_side
        stream = stream.crop(x=excess_width//2, y=excess_height//2, width=smallest_side, height=smallest_side)

    # Scale to match display
    if smallest_side != 720:
        stream = stream.filter('scale', 720, 720)

    # Different output command for images
    if in_path.endswith(('.png', '.jpg', '.jpeg')):
        stream = stream.output(out_path, vframes=1)
    else:
        stream = stream.output(out_path, vcodec='h264_v4l2m2m')

    stream.run(overwrite_output=True)
    return out_path

async def download_media(obj: TelegramObject, context: ContextTypes.DEFAULT_TYPE) -> str:
    print(f'Downloading {obj}')
    file = await context.bot.get_file(obj)
    out_file_path = f'tmp/{file.file_id}.{file.file_path.split(".")[-1]}'
    await file.download_to_drive(out_file_path)
    return out_file_path

def tgs_to_mp4(tgs_file_path: str) -> str | None:
    try:
        # A telegram sticker is just a Lottie JSON that has been gzipped
        with gzip.open(tgs_file_path) as f:
            lottie_json = json.loads(f.read())

        # Use "API" taken from https://lottietovideo.com/
        r = requests.post('https://l73mqtglr0.execute-api.eu-west-1.amazonaws.com/prod/', json={'name': 'lottietovideo', 'animation': lottie_json})
        if r.status_code != 200:
            print(f"Got error code {r.status_code} from lottietovideo API POST")
            return None

        tgs_id = r.json()['id'].split('-')[-1]

        # Wait for the video to be ready
        retry_count = 0
        while retry_count < 5 and requests.head(f"https://d2f5b11l106s2w.cloudfront.net/lottietovideo-{tgs_id}.mp4").status_code != 200:
            time.sleep(2)
            retry_count += 1

        if retry_count == 5:
            print(f"Lottietovideo API HEAD timeout")
            return None

        r = requests.get(f"https://d2f5b11l106s2w.cloudfront.net/lottietovideo-{tgs_id}.mp4")
        if r.status_code != 200:
            print(f"Got error code {r.status_code} from lottietovideo API GET")
            return None

        out_fp = f"{tgs_file_path.rstrip('.tgs')}.mp4"
        with open(out_fp, "wb") as f:
            f.write(r.content)

        return out_fp

    except Exception as e:
        print(e)
        return None

'''
The following are all handlers called by the Python Telegram Bot in response to messages from the user
'''

async def url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global insta
    insta_shortcode = update.message.text.split('/reel/')[1].split('/')[0]
    print(f"Got shortcode {insta_shortcode} from url: {update.message.text}")
    post = Post.from_shortcode(insta.context, insta_shortcode)
    insta.download_post(post, 'tmp')
    update_display(resize_media(f'tmp/{insta_shortcode}.mp4', f'out/{insta_shortcode}.mp4'))

async def sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out_file_path = await download_media(update.message.sticker, context)
    tgs_mp4 = tgs_to_mp4(out_file_path)
    if tgs_mp4 is not None:
        update_display(resize_media(tgs_mp4, f'out/{tgs_mp4.split("/")[-1]}'))

async def gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out_file_path = await download_media(update.message.animation, context)
    update_display(resize_media(out_file_path, f'out/{out_file_path.split("/")[-1]}'))

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out_file_path = await download_media(update.message.photo[-1], context)
    update_display(resize_media(out_file_path, f'out/{out_file_path.split("/")[-1]}'))


async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Got something unexpected: {update.message}")
    await context.bot.send_message(update.message.chat_id, "Sorry, I don't understand that command")


def set_brightness(percentage: int) -> None:
    value = 1023 * (1 - (percentage / 100))
    sp.run(f"gpio -g pwm 18 {value}", shell=True) # 0 is brightest, 1023 is dimmest

async def brightness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    print(f"Got brightness command with args: {context.args}")
    if len(context.args) > 0:
        try:
            set_brightness(int(context.args[0]))
            return ConversationHandler.END
        except ValueError:
            pass
    await update.message.reply_text("Now send a number between 0 and 100")
    return 0

async def brightness_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        set_brightness(int(update.message.text))
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
    if update.effective_user.id in [1158879753, 1203514639]:
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

print('About to build bot!')

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

print('Entering bot polling loop')
app.run_polling()
