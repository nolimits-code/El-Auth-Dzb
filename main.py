from datetime import datetime, timedelta
import json
import os
import random
import sqlite3
import string
import threading
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, jsonify, request

# --- CONFIGURATION ---
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = 1520249103903100979
VERIFIED_ROLE_ID = 1570807337806209207  # Updated verification role ID
REQUIRED_ADMIN_ROLE_ID = 1570762871107883039  # Required role to manage keys/setup
DB_FILE = "keys.db"

# --- FLASK API INITIALIZATION ---
app = Flask(__name__)


# --- DATABASE INITIALIZATION (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            key_str TEXT PRIMARY KEY,
            uses_count INTEGER,
            max_uses TEXT,
            duration TEXT,
            hwid_list TEXT,
            users_list TEXT,
            expires_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def load_keys():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keys")
    rows = cursor.fetchall()
    conn.close()

    keys_dict = {}
    for row in rows:
        key_str, uses_count, max_uses, duration, hwid_list, users_list, expires_at = row
        keys_dict[key_str] = {
            "uses_count": uses_count,
            "max_uses": max_uses,
            "duration": duration,
            "hwid_list": json.loads(hwid_list) if hwid_list else [],
            "users_list": json.loads(users_list) if users_list else [],
            "expires_at": expires_at if expires_at else None,
        }
    return keys_dict


def save_key(key_str, data):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO keys (key_str, uses_count, max_uses, duration, hwid_list, users_list, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            key_str,
            data.get("uses_count", 0),
            str(data.get("max_uses", "1")),
            data.get("duration", "Lifetime"),
            json.dumps(data.get("hwid_list", [])),
            json.dumps(data.get("users_list", [])),
            data.get("expires_at"),
        ),
    )
    conn.commit()
    conn.close()


def delete_key_from_db(key_str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keys WHERE key_str = ?", (key_str,))
    conn.commit()
    conn.close()


def clear_all_keys():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keys")
    conn.commit()
    conn.close()


# --- PARSE DURATION FUNCTION ---
def calculate_expiry(duration_str):
    duration_str = duration_str.strip().lower()

    if duration_str in ["lifetime", "unlimited"]:
        return "Lifetime"

    try:
        number = int(duration_str[:-1])
        unit = duration_str[-1]

        if unit == "h":
            return datetime.now() + timedelta(hours=number)
        elif unit == "d":
            return datetime.now() + timedelta(days=number)
        elif unit == "m":
            return datetime.now() + timedelta(days=number * 30)
        elif unit == "y":
            return datetime.now() + timedelta(days=number * 365)
    except Exception:
        pass

    return None


# --- FLASK API ENDPOINT ---
@app.route("/verify", methods=["GET"])
def verify_key_api():
    user_key = request.args.get("key")
    user_hwid = request.args.get("hwid")

    if not user_key:
        return jsonify({"success": False, "message": "No key provided"}), 400

    user_key = user_key.strip()
    keys_db = load_keys()

    matched_key = None
    for k in keys_db:
        if k.strip() == user_key:
            matched_key = k
            break

    if matched_key:
        key_data = keys_db[matched_key]
        hwid_list = key_data.get("hwid_list", [])

        # 1. Check Expiry
        if key_data.get("expires_at") and key_data["expires_at"] != "Lifetime":
            try:
                expire_date = datetime.fromisoformat(key_data["expires_at"])
                if datetime.now() > expire_date:
                    return jsonify({"success": False, "message": "Key expired! Please renew your key."})
            except Exception:
                pass

        max_uses_str = str(key_data.get("max_uses", "1")).lower()
        is_unlimited = max_uses_str in ["global", "unlimited", "inf"]

        # 2. Check if HWID is already registered (Re-login / Same PC)
        if user_hwid and user_hwid in hwid_list:
            return jsonify({
                "success": True,
                "message": "Key activated successfully!",
                "expiry": key_data.get("expires_at") or "Lifetime",
            })

        # 3. If it's a NEW HWID, check against Max Uses limit
        if not is_unlimited:
            try:
                max_uses = int(max_uses_str)
                if len(hwid_list) >= max_uses:
                    return jsonify({"success": False, "message": "Key limit reached! Max uses exceeded."})
            except Exception:
                pass

        # 4. Register the new HWID
        if user_hwid:
            hwid_list.append(user_hwid)
            key_data["hwid_list"] = hwid_list

        # 5. Set expiry time on first successful activation
        if not key_data.get("expires_at") or key_data.get("expires_at"] == "":
            duration_str = key_data.get("duration", "Lifetime")
            expiry = calculate_expiry(duration_str)
            key_data["expires_at"] = "Lifetime" if expiry == "Lifetime" or expiry is None else expiry.isoformat()

        # Update uses count based on unique HWIDs registered
        key_data["uses_count"] = len(hwid_list)
        save_key(matched_key, key_data)

        return jsonify({
            "success": True,
            "message": "Key activated successfully!",
            "expiry": key_data.get("expires_at") or "Lifetime",
        })
    else:
        return jsonify({"success": False, "message": "Invalid key"})


def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


# --- CUSTOM PERMISSION CHECK ---
def has_admin_or_role():
    async def predicate(interaction: discord.Interaction):
        if interaction.permissions.administrator:
            return True
         
        if interaction.guild:
            role = interaction.guild.get_role(REQUIRED_ADMIN_ROLE_ID)
            if role and role in interaction.user.roles:
                return True
                 
        await interaction.response.send_message(
            "❌ Ma 3ndkch l-permission bach t-st3mlo had l-command! (Khask l-role l-m5assas wela Admin)", 
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# --- DISCORD MODAL ---
class AuthModal(discord.ui.Modal, title="🔐 System Authentication"):
    key_input = discord.ui.TextInput(
        label="Enter your Access Key",
        placeholder="Example: NoLimite-XXXXXX",
        required=True,
        min_length=4,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_key = self.key_input.value.strip()
        keys_db = load_keys()

        matched_key = None
        for k in keys_db:
            if k.strip() == user_key:
                matched_key = k
                break

        if matched_key:
            key_data = keys_db[matched_key]
            users_list = key_data.get("users_list", [])

            if key_data.get("expires_at") and key_data["expires_at"] != "Lifetime":
                try:
                    if datetime.now() > datetime.fromisoformat(key_data["expires_at"]):
                        await interaction.response.send_message("❌ Had l-Key khlasat modatha (Expired)!", ephemeral=True)
                        return
                except Exception:
                    pass

            max_uses_str = str(key_data.get("max_uses", "1")).lower()
             
            if str(interaction.user.id) in users_list:
                role = interaction.guild.get_role(VERIFIED_ROLE_ID)
                if role and role not in interaction.user.roles:
                    await interaction.user.add_roles(role)
                await interaction.response.send_message("✅ Rak déja m-verifi!", ephemeral=True)
                return

            if max_uses_str not in ["global", "unlimited", "inf"]:
                try:
                    if len(users_list) >= int(max_uses_str):
                        await interaction.response.send_message("❌ Had l-Key wsel l-Max Uses ta3o!", ephemeral=True)
                        return
                except Exception:
                    pass

            role = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if role is None:
                await interaction.response.send_message("❌ Error: Role mal9inahch f server.", ephemeral=True)
                return

            try:
                await interaction.user.add_roles(role)

                if str(interaction.user.id) not in users_list:
                    users_list.append(str(interaction.user.id))
                    key_data["users_list"] = users_list
                    key_data["uses_count"] = len(users_list)

                if not key_data.get("expires_at"):
                    duration_str = key_data.get("duration", "Lifetime")
                    expiry = calculate_expiry(duration_str)
                    key_data["expires_at"] = "Lifetime" if expiry == "Lifetime" or expiry is None else expiry.isoformat()

                save_key(matched_key, key_data)

                embed = discord.Embed(
                    title="✅ Authentication Successful",
                    description=f"Mra7ba bik **{interaction.user.name}**! Ddit l-role {role.mention}.",
                    color=0x9B30FF,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ L-bot ma3ndouch permission bach y-3ti had l-Role.", ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ Invalid Key",
                description=f"L-Key li dakhaltha (`{user_key}`) ghalta wela ma tKantch f database.",
                color=0xFF0033,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


# --- DISCORD VIEW ---
class AuthView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Authenticate",
        style=discord.ButtonStyle.primary,
        custom_id="persistent_auth_button",
        emoji="🔑",
    )
    async def auth_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Rak déja m-verifi!", ephemeral=True)
            return

        await interaction.response.send_modal(AuthModal())


# --- SELECT MENU FOR DELETING KEYS ---
class DeleteKeySelect(discord.ui.Select):
    def __init__(self, keys_dict):
        options = [
            discord.SelectOption(
                label="DELETE ALL KEYS",
                value="DELETE_ALL_KEYS_OPTION",
                description="Mshihom ga3 f merra wa7da",
                emoji="⚠️",
            )
        ]

        for key in list(keys_dict.keys())[:24]:
            uses = keys_dict[key].get("uses_count", 0)
            max_u = keys_dict[key].get("max_uses", 1)
            status = f"Uses: {uses}/{max_u}"
            options.append(
                discord.SelectOption(label=key, description=status, emoji="🗑️")
            )

        super().__init__(
            placeholder="Khtar l-Key wela Delete All...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]

        if selected_value == "DELETE_ALL_KEYS_OPTION":
            clear_all_keys()
            await interaction.response.send_message(
                "⚠️ T-supprimaw **Ga3** les keys men database b naja7!",
                ephemeral=True,
            )
        else:
            keys_db = load_keys()
            if selected_value in keys_db:
                delete_key_from_db(selected_value)
                await interaction.response.send_message(
                    f"✅ T-supprima l-Key b naja7: `{selected_value}`", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ L-Key `{selected_value}` mal9inahch g3!", ephemeral=True
                )


class DeleteKeyView(discord.ui.View):
    def __init__(self, keys_dict):
        super().__init__(timeout=60)
        self.add_item(DeleteKeySelect(keys_dict))


# --- DISCORD BOT SETUP ---
class AuthBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(AuthView())
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        print(f"[+] Discord Bot Logged in as {self.user}")


bot = AuthBot()


# --- DISCORD SLASH COMMANDS ---
@bot.tree.command(name="setup_auth", description="Send the Authentication panel")
@has_admin_or_role()
async def setup_auth(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛡️ Server Verification & Auth",
        description=(
            "Cliki 3la l-button l-ta7t w dakhel l-**Access Key** ta3ek "
            "bach t-feta7 les salons w t-ddi l-Role."
        ),
        color=0x9B30FF,
    )
    embed.set_footer(text="Security System • Protected")
     
    await interaction.response.send_message("✅ Panel t-ab3at b naja7!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=AuthView())


@bot.tree.command(name="createkeys", description="Crea les keys NoLimite-")
@app_commands.describe(
    count="Ch7al mn key rak hab t-creari",
    duration="Time (Ex: 5h, 30d, 3m, 1y, wela Lifetime)",
    max_uses="Max Uses: ra9m (Ex: 1, 5) wela 'Global' / 'Unlimited'",
)
@has_admin_or_role()
async def createkeys(
    interaction: discord.Interaction,
    count: int,
    duration: str,
    max_uses: str,
):
    if count > 50:
        await interaction.response.send_message(
            "❌ Ma t9derch t-creari aktar mn 50 key f merra wa7da!", ephemeral=True
        )
        return

    new_keys = []

    for _ in range(count):
        random_suffix = "".join(
            random.choices(string.ascii_uppercase + string.digits, k=6)
        )
        key_str = f"NoLimite-{random_suffix}"

        key_data = {
            "uses_count": 0,
            "max_uses": max_uses,
            "duration": duration,
            "hwid_list": [],
            "users_list": [],
            "expires_at": None,
        }
        save_key(key_str, key_data)
        new_keys.append(key_str)

    keys_text = "\n".join([f"`{k}`" for k in new_keys])
    if len(keys_text) > 1900:
        keys_text = f"T-creaw {count} les keys b naja7!"

    embed = discord.Embed(
        title=f"🔑 Generated {count} Keys | Time: {duration} | Max Uses: {max_uses}",
        description=keys_text,
        color=0x00FF66,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="createfreekey", description="Crea Free Global Key t-khdem 24h w t-mshi 3nd ga3 n-nas")
@has_admin_or_role()
async def createfreekey(interaction: discord.Interaction):
    random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    key_str = f"NoLimite-Free-{random_suffix}"

    key_data = {
        "uses_count": 0,
        "max_uses": "Global",
        "duration": "24h",
        "hwid_list": [],
        "users_list": [],
        "expires_at": None,
    }

    save_key(key_str, key_data)

    embed = discord.Embed(
        title="🎁 Free Global Key Created (24h)",
        description=f"Haia l-Free Key jdida:\n\n`{key_str}`\n\n- **Type:** Global (Mzyana l ga3 n-nas)\n- **Duration:** 24 Hours (1 Day)",
        color=0xFFD700,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="deletekey", description="Affichi la list w supri ay key wela Delete All"
)
@has_admin_or_role()
async def deletekey(interaction: discord.Interaction):
    keys_db = load_keys()
    if not keys_db:
        await interaction.response.send_message(
            "❌ Ma kayn 7ta key f database bach t-supprimih.", ephemeral=True
        )
        return

    view = DeleteKeyView(keys_db)
    embed = discord.Embed(
        title="🗑️ Delete Access Key",
        description="Khtar l-Key min l-qaima wela khtar **DELETE ALL** bach t-mshihom ga3:",
        color=0xFF0033,
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="resethwid", description="Reset HWID ta3 Key m3yn")
@app_commands.describe(key="L-Key li rak hab t-resetlha l-HWID")
@has_admin_or_role()
async def resethwid(interaction: discord.Interaction, key: str):
    keys_db = load_keys()

    if key in keys_db:
        keys_db[key]["hwid_list"] = []
        keys_db[key]["uses_count"] = 0
        keys_db[key]["users_list"] = []
        save_key(key, keys_db[key])
        await interaction.response.send_message(
            f"✅ HWID w Uses t-resetlhom l-key: `{key}` b naja7!", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ L-Key `{key}` mal9inahch f database!", ephemeral=True
        )


@bot.tree.command(name="listkeys", description="Chouf les keys li kaynin m3a les details w l-performance ta3hom")
@has_admin_or_role()
async def listkeys(interaction: discord.Interaction):
    keys_db = load_keys()
    if not keys_db:
        await interaction.response.send_message(
            "❌ Ma kayn 7ta key m-creyi f database.", ephemeral=True
        )
        return

    total = len(keys_db)
    active_count = sum(1 for k in keys_db.values() if k.get("uses_count", 0) > 0)

    embed = discord.Embed(
        title="📊 Keys Status & Performance",
        description=f"Total: **{total}** | Msta3mlin: **{active_count}** | Ma zal: **{total - active_count}**\n\n**Qaima dyal Les Keys:**",
        color=0x3B82F6,
    )

    count_fields = 0
    for key_str, data in list(keys_db.items()):
        if count_fields >= 25:
            embed.add_field(
                name="⚠️ Notice", 
                value="Kaynin keys khrin ma t-affichawch kamlin hit l-limit wselna l 25.", 
                inline=False
            )
            break

        uses = data.get("uses_count", 0)
        max_uses = data.get("max_uses", "1")
        duration = data.get("duration", "Lifetime")
        expires = data.get("expires_at")
        
        if not expires:
            status_time = f"Duration: {duration} (Not activated yet)"
        elif expires == "Lifetime":
            status_time = "Lifetime ♾️"
        else:
            status_time = f"Expires: {expires[:10]}"

        field_value = (
            f"• **Uses:** `{uses}/{max_uses}`\n"
            f"• **Time:** {status_time}\n"
            f"• **HWIDs:** {len(data.get('hwid_list', []))}"
        )

        embed.add_field(
            name=f"🔑 {key_str}",
            value=field_value,
            inline=True
        )
        count_fields += 1

    embed.set_footer(text="Security System • Keys Performance")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- RUNNING BOTH FLASK & BOT CONCURRENTLY ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("[+] Flask API started on http://localhost:5000")

    bot.run(TOKEN)
