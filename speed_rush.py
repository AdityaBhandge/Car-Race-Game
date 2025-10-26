import os
import sys
import math
import random
import time
import json
import pygame
from pygame import gfxdraw
# ----------------------------- Configuration -----------------------------
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
HIGHSCORE_FILE = os.path.join(ASSETS_DIR, 'highscores.json')

SCREEN_WIDTH = 900
SCREEN_HEIGHT = 600
FPS = 60
LANE_COUNT = 4  # number of lanes on the highway
LANE_MARGIN = 80
ROAD_WIDTH = SCREEN_WIDTH - LANE_MARGIN * 2
LANE_WIDTH = ROAD_WIDTH // LANE_COUNT

# colors
COLOR_BG = (18, 18, 26)
COLOR_ROAD = (40, 40, 48)
COLOR_LANE = (200, 200, 200)
COLOR_TEXT = (240, 240, 240)

# Player / physics tuning
PLAYER_START_X = SCREEN_WIDTH // 2
PLAYER_START_Y = SCREEN_HEIGHT - 140
PLAYER_MAX_SPEED = 30.0   # tuned for visually satisfying range
PLAYER_MIN_SPEED = 6.0
PLAYER_ACCEL = 18.0       # world units per second^2 (applied using dt)
PLAYER_BRAKE = 36.0       # stronger braking
PLAYER_DRAG = 6.0         # natural drag force
PLAYER_LATERAL_ACCEL = 2200.0  # lateral control acceleration (px/s^2)
PLAYER_LATERAL_FRICTION = 8.0   # lateral friction (reduces skid)
PLAYER_HANDLING = 6.0     # legacy parameter (kept for nominal values)
LANE_CHANGE_DURATION = 0.20  # baseline lane snap time (seconds)

# Enemy spawn
ENEMY_SPAWN_INTERVAL = 900  # in ms, base; decreases with difficulty
ENEMY_SPEED_BASE = 6.0

# Powerups
POWERUP_TYPES = ['nitro', 'shield']

# Near-miss bonus (combo-based)
NEAR_MISS_DISTANCE = 180  # vertical proximity in pixels to count as a near pass
NEAR_MISS_BONUS = 250
NEAR_MISS_COMBO_WINDOW = 1500  # ms window to chain combos
NEAR_MISS_MAX_COMBO = 6
NEAR_MISS_COMBO_MULT = 0.25  # each combo step adds 25% bonus

# -------------------------------------------------------------------------

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
pygame.font.init()

# Screen and clock
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption('Speed Rush: Extreme Highway')
clock = pygame.time.Clock()

# Load assets helper

def load_image(name, scale=None, colorkey=None):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        return None
    img = pygame.image.load(path)
    # convert surfaces once for faster blitting
    try:
        img = img.convert_alpha()
    except Exception:
        img = img.convert()
    if scale:
        img = pygame.transform.smoothscale(img, scale)
    if colorkey is not None:
        img.set_colorkey(colorkey)
    return img


def load_sound(name):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        return None
    return pygame.mixer.Sound(path)


# Assets placeholders (names for user to fill)
ASSET_LIST = {
    'player': 'car_player.png',
    'enemy_car': 'car_enemy.png',
    'enemy_truck': 'truck_enemy.png',
    'enemy_bus': 'bus_enemy.png',
    'road': 'road.png',
    'bg_music': 'music_loop.ogg',
    'engine': 'engine_loop.ogg',
    'crash': 'crash.wav',
    'nitro': 'nitro.wav',
    'shield': 'shield.wav',
    'nearmiss': 'nearmiss.wav',
    'font': 'arcade.ttf'
}

# Try to load assets; if missing, we'll fallback to simple shapes/silent sounds
images = {}
sounds = {}
for k, v in ASSET_LIST.items():
    if v.endswith('.png') or v.endswith('.jpg') or v.endswith('.jpeg'):
        images[k] = load_image(v)
    elif v.endswith('.ogg') or v.endswith('.wav') or v.endswith('.mp3'):
        sounds[k] = load_sound(v)
    else:
        # font or others
        pass

# Fonts
try:
    GAME_FONT = pygame.font.Font(os.path.join(ASSETS_DIR, ASSET_LIST['font']), 20)
except Exception:
    GAME_FONT = pygame.font.SysFont('Arial', 20)

# Music
if sounds.get('bg_music'):
    try:
        pygame.mixer.music.load(os.path.join(ASSETS_DIR, ASSET_LIST['bg_music']))
        pygame.mixer.music.set_volume(0.4)
    except Exception:
        pass

# Engine sound looping channel
engine_sound = sounds.get('engine')
if engine_sound:
    engine_chan = pygame.mixer.Channel(2)
    engine_chan.play(engine_sound, loops=-1)
    engine_chan.set_volume(0.5)
else:
    engine_chan = None

# Crash sound
crash_sound = sounds.get('crash')
nitro_sound = sounds.get('nitro')
shield_sound = sounds.get('shield')
nearmiss_sound = sounds.get('nearmiss')

# Utility: save/load highscores

def load_highscores():
    if not os.path.exists(HIGHSCORE_FILE):
        return []
    try:
        with open(HIGHSCORE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_highscores(scores):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    try:
        with open(HIGHSCORE_FILE, 'w', encoding='utf-8') as f:
            json.dump(scores, f, indent=2)
    except Exception as e:
        print('Failed to save highscores:', e)


# Game entities
class Particle:
    """Simple particle for nitro trails, sparks, and smoke.
    Lightweight particle with position, velocity, life and color.
    """
    def __init__(self, x, y, vx, vy, life, color, size):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, surf):
        if self.life <= 0:
            return
        a = max(0, min(255, int(255 * (self.life / max(1e-6, self.max_life)))))
        col = (*self.color[:3], a) if len(self.color) == 4 else (*self.color, a)
        s = max(1, int(self.size * (self.life / max(1e-6, self.max_life))))
        surf_p = pygame.Surface((s*2, s*2), pygame.SRCALPHA)
        pygame.draw.circle(surf_p, col, (s, s), s)
        surf.blit(surf_p, (int(self.x - s), int(self.y - s)))


class ParticleSystem:
    def __init__(self):
        self.particles = []

    def emit(self, p: Particle):
        self.particles.append(p)

    def update(self, dt):
        for p in self.particles[:]:
            p.update(dt)
            if p.life <= 0:
                self.particles.remove(p)

    def draw(self, surf):
        for p in self.particles:
            p.draw(surf)


class Player:
    def __init__(self):
        self.image = images.get('player')
        self.width = 60
        self.height = 120
        self.x = PLAYER_START_X
        self.y = PLAYER_START_Y
        # longitudinal (forward) speed in arbitrary world units
        self.speed = 12.0
        # lateral velocity for drifting / smooth lane changes
        self.vx = 0.0
        self.lane = LANE_COUNT // 2
        # lane-change interpolation state
        self.start_x = self.x
        self.target_x = self.x
        self.lane_progress = 1.0  # 1.0 means not moving; 0..1 moving
        self.rect = pygame.Rect(0, 0, self.width, self.height)
        self.nitro = 0.0
        self.shield = 0
        self.last_lane_change_time = 0
        # particle system for nitro trails and collision sparks
        self.particles = ParticleSystem()
        # smooth HUD-interpolated displayed speed for needle animation
        self.display_speed = self.speed
        # cache scaled image to avoid per-frame scaling
        if self.image:
            try:
                self.scaled_image = pygame.transform.smoothscale(self.image, (self.width, self.height)).convert_alpha()
            except Exception:
                self.scaled_image = self.image
        else:
            self.scaled_image = None

    def update(self, dt, keys):
        # --- Longitudinal physics ---
        # Apply acceleration/brake as forces (units: px/s^2 scaled by dt)
        accel = 0.0
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            accel += PLAYER_ACCEL
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            accel -= PLAYER_BRAKE

        # Nitro adds a temporary speed multiplier
        nitro_boost = 0.0
        if self.nitro > 0:
            nitro_boost = 10.0  # boost in speed units
            self.nitro -= dt
            if self.nitro < 0:
                self.nitro = 0
            # emit nitro particles
            for i in range(2):
                jitter = random.uniform(-8, 8)
                p = Particle(self.x + jitter, self.y + self.height//2, random.uniform(-20,20), random.uniform(40,140), 0.4, (255,180,40), random.uniform(2,5))
                self.particles.emit(p)

        # drag proportional to speed
        drag = PLAYER_DRAG * (self.speed / max(1.0, PLAYER_MAX_SPEED))
        self.speed += (accel - drag) * dt
        self.speed = max(PLAYER_MIN_SPEED, min(PLAYER_MAX_SPEED + nitro_boost, self.speed))

        # --- Lateral physics (drifting and smooth lane changes) ---
        lateral_force = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            lateral_force -= PLAYER_LATERAL_ACCEL
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            lateral_force += PLAYER_LATERAL_ACCEL

        # update lateral velocity using forces
        self.vx += lateral_force * dt
        # friction
        self.vx -= self.vx * min(1.0, PLAYER_LATERAL_FRICTION * dt)

        # integrate position
        self.x += self.vx * dt

        # if not actively steering, softly snap to current lane center over time
        lane_center = LANE_MARGIN + self.lane * LANE_WIDTH + LANE_WIDTH // 2
        # compute difference and apply soft correction
        dx = lane_center - self.x
        # apply soft spring towards lane center (only when near center or not holding steering)
        if abs(dx) < LANE_WIDTH * 0.9:
            # spring force proportional to distance
            self.vx += (dx * 8.0) * dt

        # clamp within road boundaries
        min_x = LANE_MARGIN + 10
        max_x = LANE_MARGIN + ROAD_WIDTH - 10
        self.x = max(min_x, min(max_x, self.x))

        # lane_progress still used for keyboard lane change auto-snap (initiated elsewhere)
        if self.lane_progress < 1.0:
            self.lane_progress += dt / max(1e-6, LANE_CHANGE_DURATION)
            if self.lane_progress >= 1.0:
                self.lane_progress = 1.0
                self.x = self.target_x
            else:
                t = self.lane_progress
                # smoother easing (cubic)
                t = t * t * (3 - 2 * t)
                self.x = self.start_x + (self.target_x - self.start_x) * t
        # particle update (keep particles tied to player)
        self.particles.update(dt)

        # update rect
        self.rect.width = self.width
        self.rect.height = self.height
        self.rect.centerx = int(self.x)
        self.rect.centery = int(self.y)

        # smooth displayed speed for HUD needle animation
        self.display_speed += (self.speed - self.display_speed) * min(1.0, dt * 6.0)

    def draw(self, surf):
        # draw soft shadow under car
        shadow_surf = pygame.Surface((self.width, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, 100), shadow_surf.get_rect())
        surf.blit(shadow_surf, (int(self.x - self.width//2), int(self.y + self.height//2)+6))

        if self.scaled_image:
            # rotate slightly based on lateral velocity for leaning effect
            angle = max(-12, min(12, -self.vx * 0.6))
            try:
                img = pygame.transform.rotozoom(self.scaled_image, angle, 1.0)
            except Exception:
                img = pygame.transform.rotate(self.scaled_image, angle)
            rect = img.get_rect(center=(int(self.x), int(self.y)))
            surf.blit(img, rect)
        else:
            # draw a simple car shape
            pygame.draw.rect(surf, (50,200,50), self.rect, border_radius=8)

        # draw particles (nitro/sparks) behind car
        self.particles.draw(surf)


class Enemy:
    def __init__(self, kind='car'):
        self.kind = kind
        self.width = 60 if kind == 'car' else 90 if kind == 'truck' else 100
        self.height = 120 if kind == 'car' else 140
        self.lane = random.randint(0, LANE_COUNT-1)
        self.x = LANE_MARGIN + self.lane * LANE_WIDTH + LANE_WIDTH // 2
        self.y = -random.randint(100, 800)
        base = ENEMY_SPEED_BASE
        if kind == 'truck':
            base -= 1.2
        if kind == 'bus':
            base -= 0.8
        self.speed = base + random.random() * 2.0
        self.image = images.get('enemy_car') if kind == 'car' else images.get('enemy_truck') if kind == 'truck' else images.get('enemy_bus')
        self.rect = pygame.Rect(0,0,self.width,self.height)
        self.passed = False
        # cache scaled image for this enemy
        if self.image:
            try:
                self.scaled_image = pygame.transform.smoothscale(self.image, (self.width, self.height)).convert_alpha()
            except Exception:
                self.scaled_image = self.image
        else:
            self.scaled_image = None

    def update(self, dt, world_speed):
        # world_speed moves enemies down relative to player
        # speeds are treated as pixels per frame baseline; scale by dt*60 to maintain feel
        self.y += (self.speed + world_speed) * (dt * 60.0)
        self.rect.width = self.width
        self.rect.height = self.height
        self.rect.centerx = int(self.x)
        self.rect.centery = int(self.y)

    def draw(self, surf):
        if self.scaled_image:
            surf.blit(self.scaled_image, self.scaled_image.get_rect(center=(int(self.x), int(self.y))))
        else:
            color = (200,50,50) if self.kind == 'car' else (170,120,60)
            r = pygame.Rect(0,0,self.width,self.height)
            r.center = (int(self.x), int(self.y))
            pygame.draw.rect(surf, color, r, border_radius=8)
            pygame.draw.ellipse(surf, (0,0,0,100), (int(self.x - self.width//2), int(self.y + self.height//2)+4, self.width, 18))


class Powerup:
    def __init__(self, kind):
        self.kind = kind
        self.width = 48
        self.height = 48
        self.lane = random.randint(0, LANE_COUNT-1)
        self.x = LANE_MARGIN + self.lane * LANE_WIDTH + LANE_WIDTH // 2
        self.y = -random.randint(200, 1200)
        self.rect = pygame.Rect(0,0,self.width,self.height)
        self.image = images.get(kind)

    def update(self, dt, world_speed):
        # powerups drift down with world speed
        self.y += world_speed * (dt * 60.0)
        self.rect.centerx = int(self.x)
        self.rect.centery = int(self.y)

    def draw(self, surf):
        if self.image:
            img = pygame.transform.smoothscale(self.image, (self.width, self.height))
            surf.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
        else:
            c = (50,200,250) if self.kind == 'nitro' else (250,200,50)
            r = pygame.Rect(0,0,self.width,self.height)
            r.center = (int(self.x), int(self.y))
            pygame.draw.ellipse(surf, c, r)


# Road background
class Road:
    def __init__(self):
        self.y = 0.0
        self.image = images.get('road')
        # create lane line pattern surface
        self.pattern = pygame.Surface((LANE_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        # precompute lane x positions for performance
        self.lane_x = [LANE_MARGIN + i * LANE_WIDTH for i in range(1, LANE_COUNT)]
        # pre-rendered background surface for faster draw
        self.surface = pygame.Surface((ROAD_WIDTH, SCREEN_HEIGHT))
        self._render_static()
        # adaptive detail flag
        self.low_detail = False

    def _render_static(self):
        # draw static parts once to self.surface
        s = self.surface
        s.fill(COLOR_ROAD)
        for x in self.lane_x:
            step = 40
            dash_h = 30
            y = -40
            while y < SCREEN_HEIGHT:
                pygame.draw.rect(s, COLOR_LANE, (x - LANE_MARGIN - 3, y, 6, dash_h))
                y += step
        # draw road edges
        pygame.draw.rect(s, (60,60,70), (0, 0, 10, SCREEN_HEIGHT))
        pygame.draw.rect(s, (60,60,70), (ROAD_WIDTH-10, 0, 10, SCREEN_HEIGHT))

    def update(self, dt, speed):
        self.y += speed * dt * 30  # parallax factor for illusion
        if self.y > SCREEN_HEIGHT:
            self.y -= SCREEN_HEIGHT

    def draw(self, surf):
        # blit pre-rendered road and then overlay moving dashes for illusion of motion
        surf.blit(self.surface, (LANE_MARGIN, 0))
        # moving dashes (only if high detail)
        if not self.low_detail:
            for x in self.lane_x:
                step = 40
                dash_h = 30
                start = -40 + int(self.y) % step
                y = start
                while y < SCREEN_HEIGHT:
                    pygame.draw.rect(surf, COLOR_LANE, (x-3, y, 6, dash_h))
                    y += step

# POV mode: 'third' or 'first' (driver view)
POV_MODE = 'third'  # default to third-person / original view


def perspective_for_enemy(e_y, player_y):
    """Return normalized depth [0..1], scale and screen y for enemy based on world y."""
    # Map enemy world y to a normalized depth. Enemies with lower y are farther.
    # Add offsets to tune the perspective feel.
    z = (e_y + 400.0) / (SCREEN_HEIGHT + 800.0)
    z = max(0.0, min(1.0, z))
    # scale range: far (0) -> small, near (1) -> larger
    scale = 0.45 + 1.1 * z
    # screen y ranges from near top (50) to near player_y-80
    screen_y = 60 + z * (player_y - 120 - 60)
    return z, scale, int(screen_y)


def draw_enemy_pov(surf, e, player, low_detail=False):
    # compute perspective
    z, scale, sy = perspective_for_enemy(e.y, player.y)
    # apply lane contraction to x
    center = SCREEN_WIDTH // 2
    contraction = 0.6 + 0.4 * z
    sx = center + int((e.x - center) * contraction)

    if e.scaled_image:
        w = max(8, int(e.width * scale))
        h = max(12, int(e.height * scale))
        try:
            img = pygame.transform.smoothscale(e.scaled_image, (w, h))
        except Exception:
            img = pygame.transform.scale(e.scaled_image, (w, h))
        rect = img.get_rect(center=(sx, sy))
        surf.blit(img, rect)
    else:
        w = max(8, int(e.width * scale))
        h = max(12, int(e.height * scale))
        r = pygame.Rect(0, 0, w, h)
        r.center = (sx, sy)
        color = (200, 50, 50) if e.kind == 'car' else (170,120,60)
        pygame.draw.rect(surf, color, r, border_radius=max(2, w//8))

    # update enemy rect for collision using scaled dims and screen coords
    e.rect.width = int(e.width * scale)
    e.rect.height = int(e.height * scale)
    e.rect.centerx = sx
    e.rect.centery = sy


def draw_player_pov(surf, player):
    # draw hood/dashboard at bottom center. If player image has a hood variant use it.
    hood_h = int(player.height * 0.6)
    hood_w = int(player.width * 1.6)
    cx = SCREEN_WIDTH // 2
    cy = SCREEN_HEIGHT - int(player.height * 0.25)
    if player.scaled_image:
        # scale player's image to a hood-like shape and blit at bottom
        try:
            hood = pygame.transform.smoothscale(player.scaled_image, (hood_w, hood_h))
        except Exception:
            hood = pygame.transform.scale(player.scaled_image, (hood_w, hood_h))
        surf.blit(hood, hood.get_rect(center=(cx, cy)))
    else:
        # draw simple dashboard/hood
        hood_rect = pygame.Rect(0,0,hood_w, hood_h)
        hood_rect.center = (cx, cy)
        pygame.draw.ellipse(surf, (40,120,200), hood_rect)
        pygame.draw.rect(surf, (20,20,20), (0, SCREEN_HEIGHT-60, SCREEN_WIDTH, 60))



# UI helpers

def draw_text(surf, text, size, x, y, color=COLOR_TEXT, center=False):
    # cache font objects by size for performance
    if not hasattr(draw_text, 'font_cache'):
        draw_text.font_cache = {}
    if size not in draw_text.font_cache:
        draw_text.font_cache[size] = pygame.font.Font(None, size)
    font = draw_text.font_cache[size]
    surf_text = font.render(str(text), True, color)
    rect = surf_text.get_rect()
    if center:
        rect.center = (x, y)
    else:
        rect.topleft = (x, y)
    surf.blit(surf_text, rect)


def format_score(s):
    return '{:07d}'.format(int(s))


def draw_hud(surf, player, score, fps):
    """Draw an improved HUD: speedometer, nitro meter, shield count and score.
    Uses player.display_speed for a smoothed needle animation.
    """
    # score top-left
    draw_text(surf, f'Score: {format_score(score)}', 28, 12, 8)
    # FPS top-right
    draw_text(surf, f'FPS: {int(fps)}', 18, SCREEN_WIDTH-120, 10)
    # Shield count
    draw_text(surf, f'Shield: {player.shield}', 18, SCREEN_WIDTH-260, 10)

    # Nitro meter (left)
    nm_x = 18
    nm_y = SCREEN_HEIGHT - 120
    nm_w = 18
    nm_h = 96
    pygame.draw.rect(surf, (40,40,40), (nm_x, nm_y, nm_w, nm_h), border_radius=6)
    if player.nitro > 0:
        fill_h = int((player.nitro / 3.0) * (nm_h-4))
        pygame.draw.rect(surf, (255,120,20), (nm_x+2, nm_y + nm_h-2-fill_h, nm_w-4, fill_h), border_radius=4)
    draw_text(surf, 'NITRO', 12, nm_x + nm_w + 8, nm_y + nm_h//2 - 6)

    # Speedometer (bottom-right)
    sp_cx = SCREEN_WIDTH - 110
    sp_cy = SCREEN_HEIGHT - 80
    sp_r = 64
    # dial
    pygame.draw.circle(surf, (24,24,24), (sp_cx, sp_cy), sp_r)
    pygame.draw.circle(surf, (12,12,12), (sp_cx, sp_cy), sp_r-8)
    # tick marks
    for i in range(0, 11):
        ang = math.radians(180 + (i * 18))
        x1 = sp_cx + int((sp_r-6) * math.cos(ang))
        y1 = sp_cy + int((sp_r-6) * math.sin(ang))
        x2 = sp_cx + int((sp_r-16) * math.cos(ang))
        y2 = sp_cy + int((sp_r-16) * math.sin(ang))
        pygame.draw.line(surf, (80,80,80), (x1,y1), (x2,y2), 2)
    # needle using smoothed display_speed
    pct = (player.display_speed - PLAYER_MIN_SPEED) / max(1.0, PLAYER_MAX_SPEED - PLAYER_MIN_SPEED)
    pct = max(0.0, min(1.0, pct))
    needle_ang = math.radians(180 + pct * 180)
    nx = sp_cx + int((sp_r-20) * math.cos(needle_ang))
    ny = sp_cy + int((sp_r-20) * math.sin(needle_ang))
    pygame.draw.line(surf, (255,80,40), (sp_cx, sp_cy), (nx, ny), 4)
    draw_text(surf, f'{int(player.display_speed):03d}', 18, sp_cx, sp_cy + sp_r - 18, center=True)


# Main Game

def main_menu():
    selected = 0
    options = ['Start Game', 'Instructions', 'High Scores', 'Quit']
    t0 = time.time()
    if pygame.mixer.music.get_busy() == False and sounds.get('bg_music'):
        try:
            pygame.mixer.music.play(-1)
        except Exception:
            pass

    while True:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_DOWN:
                    selected = (selected + 1) % len(options)
                if event.key == pygame.K_UP:
                    selected = (selected - 1) % len(options)
                if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                    choice = options[selected]
                    if choice == 'Start Game':
                        return
                    if choice == 'Instructions':
                        show_instructions()
                    if choice == 'High Scores':
                        show_highscores()
                    if choice == 'Quit':
                        pygame.quit(); sys.exit()

        # Draw
        screen.fill(COLOR_BG)
        draw_text(screen, 'Speed Rush: Extreme Highway', 48, SCREEN_WIDTH//2, 60, center=True)

        # Animated car icon
        px = SCREEN_WIDTH//2
        py = 160 + math.sin(time.time()*2.0)*6
        if images.get('player'):
            img = pygame.transform.smoothscale(images['player'], (120, 240))
            screen.blit(img, img.get_rect(center=(px, py)))
        else:
            pygame.draw.rect(screen, (50,200,50), pygame.Rect(px-60, py-120, 120, 240), border_radius=12)

        # Options
        for i, opt in enumerate(options):
            color = (255,220,60) if i == selected else COLOR_TEXT
            draw_text(screen, opt, 36, SCREEN_WIDTH//2, 300 + i*54, color, center=True)

        draw_text(screen, 'Press ENTER to select • Use UP/DOWN to navigate', 20, SCREEN_WIDTH//2, SCREEN_HEIGHT-40, center=True)

        pygame.display.flip()


def show_instructions():
    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                running = False

        screen.fill(COLOR_BG)
        lines = [
            'Instructions',
            '',
            'Drive with LEFT/RIGHT or A/D to change lanes.',
            'UP/Down or W/S to accelerate/brake slightly.',
            'Press P to pause. Pass cars to score points.',
            'Collect Nitro for a 3s speed boost, Shield prevents one crash.',
            '',
            'Press ENTER or ESC to return.'
        ]
        for i, l in enumerate(lines):
            draw_text(screen, l, 26 if i==0 else 20, 40, 40 + i*34)
        pygame.display.flip()


def show_highscores():
    running = True
    scores = load_highscores()
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                running = False

        screen.fill(COLOR_BG)
        draw_text(screen, 'High Scores', 48, SCREEN_WIDTH//2, 40, center=True)
        if not scores:
            draw_text(screen, 'No highscores yet. Play to create one!', 24, SCREEN_WIDTH//2, 140, center=True)
        else:
            for i, s in enumerate(scores[:10]):
                draw_text(screen, f'{i+1}. {s}', 28, SCREEN_WIDTH//2, 120 + i*36, center=True)

        draw_text(screen, 'Press ENTER or ESC to return', 18, SCREEN_WIDTH//2, SCREEN_HEIGHT-40, center=True)
        pygame.display.flip()


# Pause menu

def pause_menu():
    paused = True
    while paused:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_p:
                    paused = False
                if event.key == pygame.K_ESCAPE:
                    paused = False
        draw_text(screen, 'PAUSED - Press P to resume', 36, SCREEN_WIDTH//2, SCREEN_HEIGHT//2, center=True)
        pygame.display.flip()


# Game over screen
def game_over_screen(score):
    scores = load_highscores()
    try:
        scores.append(int(score))
        scores = sorted(scores, reverse=True)[:20]
        save_highscores(scores)
    except Exception:
        pass

    t0 = time.time()
    while True:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    return
                if event.key == pygame.K_ESCAPE:
                    return

        screen.fill((12,12,18))
        draw_text(screen, 'GAME OVER', 72, SCREEN_WIDTH//2, 120, center=True)
        draw_text(screen, f'Score: {format_score(score)}', 36, SCREEN_WIDTH//2, 210, center=True)
        draw_text(screen, 'Press ENTER to return to Menu', 20, SCREEN_WIDTH//2, 320, center=True)
        # animated wreck (simple)
        pygame.draw.circle(screen, (200,40,40), (SCREEN_WIDTH//2, 420), int(40 + math.sin(time.time()*6)*6))
        pygame.display.flip()


# Core game loop

def game_loop():
    # init
    player = Player()
    road = Road()
    enemies = []
    powerups = []
    # world particle system for sparks, roadside smoke, etc.
    world_particles = ParticleSystem()
    last_spawn = pygame.time.get_ticks()
    last_power = pygame.time.get_ticks()
    score = 0
    run = True
    difficulty = 1.0
    spawn_interval = ENEMY_SPAWN_INTERVAL

    # FPS smoothing for adaptive detail
    fps_samples = []
    FPS_SAMPLE_COUNT = 30
    ENEMY_CAP_LOW = 8
    ENEMY_CAP_HIGH = 28

    # local cooldown for lane changes (to avoid instant teleport)
    lane_change_cooldown = 0.18
    lane_timer = 0.0
    popups = []  # list of (text, expiry_time, x, y)
    # near-miss combo state
    near_combo_count = 0
    near_last_time = 0

    while run:
        dt_ms = clock.tick(FPS)
        dt = dt_ms / 1000.0
        keys = pygame.key.get_pressed()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_p:
                    pause_menu()
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    if lane_timer <= 0:
                        new_lane = max(0, player.lane-1)
                        if new_lane != player.lane:
                            # start lane interpolation
                            player.start_x = player.x
                            player.lane = new_lane
                            player.target_x = LANE_MARGIN + player.lane * LANE_WIDTH + LANE_WIDTH // 2
                            player.lane_progress = 0.0
                            player.last_lane_change_time = pygame.time.get_ticks()
                            # check near-miss on lane change: any enemy in that lane near player's y?
                            nowt = player.last_lane_change_time
                            for e in enemies:
                                if e.lane == new_lane and abs(e.y - player.y) < NEAR_MISS_DISTANCE:
                                    # compute combo
                                    nowt = pygame.time.get_ticks()
                                    if nowt - near_last_time <= NEAR_MISS_COMBO_WINDOW:
                                        near_combo_count = min(NEAR_MISS_MAX_COMBO, near_combo_count + 1)
                                    else:
                                        near_combo_count = 1
                                    near_last_time = nowt
                                    bonus = int(NEAR_MISS_BONUS * (1.0 + (near_combo_count-1) * NEAR_MISS_COMBO_MULT))
                                    score += bonus
                                    # play sound
                                    if nearmiss_sound:
                                        try:
                                            nearmiss_sound.play()
                                        except Exception:
                                            pass
                                    popups.append((f'NEAR MISS x{near_combo_count} +{bonus}', pygame.time.get_ticks() + 1400, player.x, player.y - 120))
                                    break
                            lane_timer = lane_change_cooldown
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    if lane_timer <= 0:
                        new_lane = min(LANE_COUNT-1, player.lane+1)
                        if new_lane != player.lane:
                            player.start_x = player.x
                            player.lane = new_lane
                            player.target_x = LANE_MARGIN + player.lane * LANE_WIDTH + LANE_WIDTH // 2
                            player.lane_progress = 0.0
                            player.last_lane_change_time = pygame.time.get_ticks()
                            # check near-miss on lane change
                            for e in enemies:
                                if e.lane == new_lane and abs(e.y - player.y) < NEAR_MISS_DISTANCE:
                                    nowt = pygame.time.get_ticks()
                                    if nowt - near_last_time <= NEAR_MISS_COMBO_WINDOW:
                                        near_combo_count = min(NEAR_MISS_MAX_COMBO, near_combo_count + 1)
                                    else:
                                        near_combo_count = 1
                                    near_last_time = nowt
                                    bonus = int(NEAR_MISS_BONUS * (1.0 + (near_combo_count-1) * NEAR_MISS_COMBO_MULT))
                                    score += bonus
                                    if nearmiss_sound:
                                        try:
                                            nearmiss_sound.play()
                                        except Exception:
                                            pass
                                    popups.append((f'NEAR MISS x{near_combo_count} +{bonus}', pygame.time.get_ticks() + 1400, player.x, player.y - 120))
                                    break
                            lane_timer = lane_change_cooldown

        lane_timer = max(0.0, lane_timer - dt)

        # Update difficulty with score/time
        difficulty = 1.0 + (score // 1000) * 0.1
        world_speed = (player.speed - 8.0) * (1 + (score/5000.0))

        # Enemy spawning
        now = pygame.time.get_ticks()
        current_spawn_interval = max(220, int(spawn_interval / difficulty))
        if now - last_spawn > current_spawn_interval:
            last_spawn = now
            # choose kind with weights
            kind = random.choices(['car','truck','bus'], weights=[70,20,10])[0]
            e = Enemy(kind)
            # ensure no spawn directly on top of another in lane
            safe = True
            for ex in enemies:
                if ex.lane == e.lane and abs(ex.y - e.y) < 200:
                    safe = False
                    break
            if safe:
                enemies.append(e)

        # Powerup spawn occasionally
        if now - last_power > 6000:
            last_power = now
            if random.random() < 0.2:
                pu = Powerup(random.choice(POWERUP_TYPES))
                powerups.append(pu)

        # Update entities
        player.update(dt, keys)
        road.update(dt, player.speed)
        for e in enemies:
            e.update(dt, world_speed)
        for pu in powerups:
            pu.update(dt, world_speed)
        # update global particles
        world_particles.update(dt)

        # Collision detection & scoring
        # Determine collision rect for player depending on POV
        if POV_MODE == 'first':
            # create a narrow front collision rect near the hood area
            hood_w = int(player.width * 1.2)
            hood_h = int(player.height * 0.35)
            player_front_rect = pygame.Rect(0,0,hood_w, hood_h)
            player_front_rect.center = (SCREEN_WIDTH//2, SCREEN_HEIGHT - int(player.height*0.45))
        else:
            player_front_rect = player.rect

        for e in enemies[:]:
            if e.rect.colliderect(player_front_rect):
                if player.shield > 0:
                    player.shield -= 1
                    enemies.remove(e)
                    if shield_sound:
                        shield_sound.play()
                else:
                    # crash: emit spark particles, play sound, show brief impact then game over
                    if crash_sound:
                        crash_sound.play()
                    # emit a burst of sparks at player's position
                    for i in range(18):
                        ang = random.uniform(-math.pi/2 - 0.6, -math.pi/2 + 0.6)
                        speed = random.uniform(120, 420)
                        vx = math.cos(ang) * speed
                        vy = math.sin(ang) * speed
                        p = Particle(player.x + random.uniform(-20,20), player.y + random.uniform(-20,20), vx, vy, random.uniform(0.5,1.0), (255,200,60), random.uniform(2,5))
                        world_particles.emit(p)
                    # render one frame to show the sparks and then delay slightly for effect
                    road.draw(screen)
                    for ex in sorted(enemies, key=lambda x: x.y):
                        ex.draw(screen)
                    player.draw(screen)
                    world_particles.draw(screen)
                    pygame.display.flip()
                    pygame.time.delay(350)
                    game_over_screen(score)
                    return
            # scoring: if enemy passed player (y > player.y) and not counted
            if not e.passed and e.y > player.y:
                e.passed = True
                score += 100

            # remove if off bottom
            if e.y > SCREEN_HEIGHT + 200:
                enemies.remove(e)

        for pu in powerups[:]:
            if pu.rect.colliderect(player.rect):
                if pu.kind == 'nitro':
                    player.nitro = 3.0
                    player.speed = min(PLAYER_MAX_SPEED+6, player.speed+4)
                    if nitro_sound:
                        nitro_sound.play()
                if pu.kind == 'shield':
                    player.shield += 1
                    if shield_sound:
                        shield_sound.play()
                powerups.remove(pu)

        # Dynamic difficulty influences
        # increase spawn density and enemy base speed
        ENEMY_SPEED_BASE_local = ENEMY_SPEED_BASE + difficulty * 0.3
        # Update engine sound pitch/volume based on speed if available
        if engine_chan and engine_sound:
            vol = 0.3 + (player.speed - PLAYER_MIN_SPEED)/ (PLAYER_MAX_SPEED-PLAYER_MIN_SPEED) * 0.7
            engine_chan.set_volume(min(1.0, vol))

        # adaptive LOD: average FPS and reduce detail if low
        fps_samples.append(clock.get_fps())
        if len(fps_samples) > FPS_SAMPLE_COUNT:
            fps_samples.pop(0)
        avg_fps = sum(fps_samples)/len(fps_samples) if fps_samples else FPS
        if avg_fps < 40:
            road.low_detail = True
            # cap enemies
            if len(enemies) > ENEMY_CAP_LOW:
                # remove oldest off-screen or far-away enemies
                enemies = enemies[-ENEMY_CAP_LOW:]
        else:
            road.low_detail = False
            # allow more enemies up to high cap
            if len(enemies) > ENEMY_CAP_HIGH:
                enemies = enemies[-ENEMY_CAP_HIGH:]

        # Drawing
        screen.fill(COLOR_BG)
        road.draw(screen)

        # draw enemies sorted by y for pseudo-3D overlap / perspective
        if POV_MODE == 'first':
            for e in sorted(enemies, key=lambda x: x.y):
                draw_enemy_pov(screen, e, player, low_detail=road.low_detail)
        else:
            for e in sorted(enemies, key=lambda x: x.y):
                e.draw(screen)

        # draw powerups
        for pu in powerups:
            pu.draw(screen)

        # draw player POV or third-person
        if POV_MODE == 'first':
            draw_player_pov(screen, player)
        else:
            player.draw(screen)

        # draw world particles (sparks, smoke) on top of world but below HUD
        world_particles.draw(screen)

        # UI overlay (now richer)
        draw_hud(screen, player, score, clock.get_fps())

        # popups
        nowt = pygame.time.get_ticks()
        for p in popups[:]:
            text, expiry, px, py = p
            if expiry < nowt:
                popups.remove(p)
                continue
            # floating fade effect
            remaining = expiry - nowt
            alpha = max(40, min(255, int(255 * (remaining / 1200.0))))
            # draw text with a semi-transparent bg
            surf = pygame.Surface((300, 36), pygame.SRCALPHA)
            surf.fill((20,20,20, max(80, alpha//2)))
            font = pygame.font.Font(None, 26)
            txt = font.render(text, True, (255,220,60))
            surf.blit(txt, (8,6))
            screen.blit(surf, surf.get_rect(center=(int(px), int(py))))

        pygame.display.flip()

    # end loop


if __name__ == '__main__':
    # ensure assets dir exists
    os.makedirs(ASSETS_DIR, exist_ok=True)
    # simple welcoming message
    main_menu()
    while True:
        game_loop()
        # after game over return to main menu
        main_menu()
import os
import pygame
import sys

# ------------------- Paths -------------------
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)

# ------------------- Pygame Init -------------------
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
pygame.font.init()

# ------------------- Helper functions -------------------
def load_image(name, scale=None, colorkey=None):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        print(f"[WARN] Image not found: {name}")
        return None
    img = pygame.image.load(path)
    try:
        img = img.convert_alpha()
    except Exception:
        img = img.convert()
    if scale:
        img = pygame.transform.smoothscale(img, scale)
    if colorkey is not None:
        img.set_colorkey(colorkey)
    return img

def load_sound(name):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        print(f"[WARN] Sound not found: {name}")
        return None
    return pygame.mixer.Sound(path)

def load_font(name, size):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        print(f"[WARN] Font not found: {name}, using default")
        return pygame.font.SysFont('Arial', size)
    try:
        return pygame.font.Font(path, size)
    except Exception as e:
        print(f"[WARN] Failed to load font {name}: {e}")
        return pygame.font.SysFont('Arial', size)

# ------------------- Assets -------------------
ASSET_LIST = {
    'player': 'car_player.png',
    'enemy_car': 'car_enemy.png',
    'enemy_truck': 'truck_enemy.png',
    'enemy_bus': 'bus_enemy.png',
    'road': 'road.png',
    'bg_music': 'music_loop.ogg',
    'engine': 'engine_loop.ogg',
    'crash': 'crash.wav',
    'nitro': 'nitro.wav',
    'shield': 'shield.wav',
    'nearmiss': 'nearmiss.wav',
    'font': 'arcade.ttf'
}

images = {}
sounds = {}

# Load all images and sounds
for key, file in ASSET_LIST.items():
    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
        images[key] = load_image(file)
    elif file.lower().endswith(('.wav', '.mp3', '.ogg')):
        sounds[key] = load_sound(file)

# Fonts
GAME_FONT = load_font(ASSET_LIST.get('font',''), 20)

# ------------------- Music -------------------
if sounds.get('bg_music'):
    try:
        pygame.mixer.music.load(os.path.join(ASSETS_DIR, ASSET_LIST['bg_music']))
        pygame.mixer.music.set_volume(0.4)
        pygame.mixer.music.play(-1)
    except Exception as e:
        print(f"[WARN] Failed to play bg music: {e}")

# Engine sound looping
engine_sound = sounds.get('engine')
if engine_sound:
    try:
        engine_chan = pygame.mixer.Channel(2)
        engine_chan.play(engine_sound, loops=-1)
        engine_chan.set_volume(0.5)
    except Exception as e:
        print(f"[WARN] Failed to play engine sound: {e}")
        engine_chan = None
else:
    engine_chan = None

# Crash, nitro, shield, nearmiss sounds
crash_sound = sounds.get('crash')
nitro_sound = sounds.get('nitro')
shield_sound = sounds.get('shield')
nearmiss_sound = sounds.get('nearmiss')
if __name__ == "__main__":
    while True:
        main_menu()
        game_loop()
        game_over_screen(0)  # pass the final score here, modify in your game loop

if __name__ == "__main__":
    while True:
        main_menu()
        game_loop()
        # Pass actual score from game loop; currently zero
        game_over_screen(0)

print("All assets loaded safely. Ready to run game code!")
if engine_chan:
    try:
        engine_chan.play(engine_sound, loops=-1)
    except Exception:
        pass
# Background music
pygame.mixer.music.load('music_loop.ogg')
pygame.mixer.music.set_volume(0.5)  # adjust volume
pygame.mixer.music.play(-1)  # -1 means loop forever

# Engine sound (looping)
engine_sound = pygame.mixer.Sound('engine_loop.ogg')
engine_sound.set_volume(0.7)
engine_channel = pygame.mixer.Channel(0)
engine_channel.play(engine_sound, loops=-1)  # loops=-1 for infinite loop

# Crash sound (one-time)
crash_sound = pygame.mixer.Sound('crash.wav')
crash_sound.set_volume(1.0)
import pygame
import sys

# Initialize Pygame
pygame.init()
pygame.mixer.pre_init(44100, -16, 2, 512)

# Screen setup
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Car Game Demo")

# Load images
car_image = pygame.image.load("car.png")
car_rect = car_image.get_rect(center=(WIDTH//2, HEIGHT//2))

# Load sounds
engine_sound = pygame.mixer.Sound("engine_loop.ogg")
engine_sound.set_volume(0.5)
crash_sound = pygame.mixer.Sound("crash.wav")
crash_sound.set_volume(0.7)

# Load and play background music (looping)
pygame.mixer.music.load("music_loop.ogg")
pygame.mixer.music.set_volume(0.3)
pygame.mixer.music.play(-1)  # -1 = loop indefinitely

# Play engine sound in a loop
engine_channel = pygame.mixer.Channel(0)
engine_channel.play(engine_sound, loops=-1)

# Game loop
running = True
while running:
    screen.fill((50, 150, 50))  # Green background
    screen.blit(car_image, car_rect)  # Draw car
    
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        
        # Press SPACE to play crash sound
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                crash_sound.play()
    
    pygame.display.update()

pygame.quit()
sys.exit()
import pygame
import sys

pygame.init()

# Window setup
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Car Display")

# Load car image
car_image = pygame.image.load("car.png")
car_rect = car_image.get_rect(center=(WIDTH // 2, HEIGHT // 2))

# Game loop
running = True
while running:
    screen.fill((50, 150, 50))  # Background color
    screen.blit(car_image, car_rect)  # Draw car image
    
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    pygame.display.update()

pygame.quit()
sys.exit()
