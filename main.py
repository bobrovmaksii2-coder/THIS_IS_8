import os
import random
import math

from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.graphics import Color, RoundedRectangle, Ellipse, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.progressbar import ProgressBar
from kivy.uix.image import Image as KivyImage

# Папка, где лежит сам скрипт — так пути к картинкам работают
# независимо от того, откуда запущен Pydroid 3.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def image_path(filename: str) -> str:
    return os.path.join(BASE_DIR, "images", filename)

# ============================================================
#  ТАБЛИЦА РЕДКОСТЕЙ
#  (название, верхняя граница из 10000, цвет)
#  Чем выше число во втором элементе — тем "правее" редкость
#  находится в диапазоне 1..10000, и тем она реже выпадает.
# ============================================================
RARITIES = [
    ("Обычная",      6000,  (0.6, 0.6, 0.7, 1)),
    ("Необычная",    8000,  (0.0, 0.9, 0.4, 1)),
    ("Редкая",       9000,  (0.0, 0.6, 1.0, 1)),
    ("Эпическая",    9500,  (0.7, 0.2, 0.9, 1)),
    ("Мифическая",   9800,  (1.0, 0.0, 0.4, 1)),
    ("Легендарная",  9950,  (1.0, 0.5, 0.0, 1)),
    ("Божественная", 9985,  (1.0, 0.9, 0.0, 1)),
    ("Древняя",      9995,  (0.0, 1.0, 0.9, 1)),
    ("Проклятая",    9999,  (0.5, 0.0, 0.0, 1)),
    ("НЕВОЗМОЖНАЯ",  10000, (1.0, 1.0, 1.0, 1)),
]

# Индекс редкости, начиная с которого пити-счётчик сбрасывается
# (0 = Обычная, 1 = Необычная, 2 = Редкая, ...)
RARE_THRESHOLD_INDEX = 2

# ============================================================
#  КАРТИНКИ ДЛЯ РЕДКОСТЕЙ
#  Файлы должны лежать в папке "images" рядом со скриптом.
#  Если для редкости картинки нет — просто не добавляй её сюда,
#  тогда покажется обычная цветная плашка без фото.
# ============================================================
RARITY_IMAGES = {
    "Обычная": image_path("obychnaya.jpg"),
    "Редкая": image_path("redkaya.jpg"),
    "Эпическая": image_path("epicheskaya.jpg"),
    "НЕВОЗМОЖНАЯ": image_path("nevozmozhnaya.jpg"),
}

# Сколько бросков подряд без "Редкой+" гарантируют её выпадение
HARD_PITY = 40

# Насколько сильно растёт "мягкий" шанс с каждым броском без удачи
SOFT_PITY_STEP = 45
SOFT_PITY_CAP = 3200


def rarity_chance_percent(index: int) -> float:
    """Шанс редкости с данным индексом в процентах (без учёта пити)."""
    upper = RARITIES[index][1]
    lower = RARITIES[index - 1][1] if index > 0 else 0
    return (upper - lower) / 100


# ============================================================
#  ВИЗУАЛЬНЫЕ ЭФФЕКТЫ
# ============================================================

class Particle(Widget):
    """Маленькая частица, разлетающаяся от места ролла и гаснущая."""

    alpha = NumericProperty(1.0)

    def __init__(self, color, **kwargs):
        super().__init__(**kwargs)
        self.size = (dp(10), dp(10))
        with self.canvas:
            self.color_instr = Color(color[0], color[1], color[2], self.alpha)
            self.ellipse = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync, alpha=self._sync_alpha)

    def _sync(self, *_args):
        self.ellipse.pos = self.pos
        self.ellipse.size = self.size

    def _sync_alpha(self, *_args):
        self.color_instr.a = self.alpha


class FlashOverlay(Widget):
    """Полноэкранная вспышка для самых топовых редкостей."""

    alpha = NumericProperty(0.55)

    def __init__(self, color=(1, 1, 1), **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self.color_instr = Color(color[0], color[1], color[2], self.alpha)
            self.rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync, alpha=self._sync_alpha)

    def _sync(self, *_args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def _sync_alpha(self, *_args):
        self.color_instr.a = self.alpha


class ModernButton(Button):
    """Кнопка со скруглёнными углами и заливкой вместо стандартной текстуры."""

    def __init__(self, bg_color=(0.2, 0.2, 0.25, 1), radius=None, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.bg_color = bg_color
        self.radius = radius or [20]
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *_args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self.disabled:
                Color(self.bg_color[0] * 0.4, self.bg_color[1] * 0.4,
                      self.bg_color[2] * 0.4, 1)
            else:
                Color(*self.bg_color)
            RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)


# ============================================================
#  ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ============================================================

class RngClickerGame(App):

    def build(self):
        self.score = 0
        self.inventory = {r[0]: 0 for r in RARITIES}
        self.pity_counter = 0
        self._flicker_event = None

        # --- Корневой контейнер на весь экран, фон рисуется здесь,
        #     чтобы шейк-эффект его не сдвигал.
        self.root_float = FloatLayout()
        with self.root_float.canvas.before:
            Color(0.07, 0.07, 0.1, 1)
            self.main_bg_rect = RoundedRectangle(
                pos=self.root_float.pos, size=self.root_float.size
            )
        self.root_float.bind(pos=self._update_main_bg, size=self._update_main_bg)

        # --- Обёртка, которую будем трясти при топовых редкостях
        self.shake_wrapper = FloatLayout(size_hint=(1, 1))

        main_layout = BoxLayout(
            orientation="vertical", padding=dp(30), spacing=dp(18),
            size_hint=(1, 1),
        )

        # 1. Статус-бар: счётчик кликов + пити-счётчик
        status_row = BoxLayout(size_hint_y=0.08, spacing=dp(10))
        self.score_label = Label(
            text=f"КЛИКОВ: {self.score}",
            font_size="16sp", bold=True, color=(0.55, 0.55, 0.65, 1),
            halign="left", valign="middle",
        )
        self.score_label.bind(size=lambda s, w: setattr(s, "text_size", w))
        self.pity_label = Label(
            text=f"ПИТИ: 0/{HARD_PITY}",
            font_size="16sp", bold=True, color=(0.55, 0.55, 0.65, 1),
            halign="right", valign="middle",
        )
        self.pity_label.bind(size=lambda s, w: setattr(s, "text_size", w))
        status_row.add_widget(self.score_label)
        status_row.add_widget(self.pity_label)
        main_layout.add_widget(status_row)

        # 2. Полоска прогресса до гарантированной редкой+
        self.pity_bar = ProgressBar(max=HARD_PITY, value=0, size_hint_y=0.04)
        main_layout.add_widget(self.pity_bar)

        # 3. Витрина результата (картинка сверху + текст снизу)
        self.display_box = BoxLayout(
            orientation="vertical", padding=dp(16), spacing=dp(8), size_hint_y=0.4
        )
        with self.display_box.canvas.before:
            self.display_bg = Color(0.12, 0.12, 0.18, 1)
            self.display_rect = RoundedRectangle(
                pos=self.display_box.pos, size=self.display_box.size, radius=[25]
            )
        self.display_box.bind(pos=self._update_display_rect, size=self._update_display_rect)

        # Картинка редкости — по умолчанию скрыта (size_hint_y=0),
        # появляется только когда для выбитой редкости есть фото.
        self.drop_image = KivyImage(
            allow_stretch=True, keep_ratio=True, size_hint_y=0, opacity=0
        )
        self.display_box.add_widget(self.drop_image)

        self.drop_label = Label(
            text="НАЖМИ НА КНОПКУ\nИСПЫТАЙ СВОЙ RNG",
            font_size="24sp", bold=True, halign="center", valign="middle",
            color=(0.4, 0.4, 0.5, 1),
        )
        self.drop_label.bind(size=lambda s, w: setattr(s, "text_size", w))
        self.display_box.add_widget(self.drop_label)
        main_layout.add_widget(self.display_box)

        # 4. Кнопка ролла
        self.click_button = ModernButton(
            text="ИСПЫТАТЬ УДАЧУ", font_size="26sp", bold=True,
            bg_color=(0.1, 0.5, 1.0, 1), size_hint_y=0.28, radius=[25],
        )
        self.click_button.bind(on_press=self.on_click)
        main_layout.add_widget(self.click_button)

        # 5. Кнопка инвентаря
        self.inv_button = ModernButton(
            text="💼 ОТКРЫТЬ ИНВЕНТАРЬ", font_size="16sp", bold=True,
            bg_color=(0.18, 0.18, 0.24, 1), size_hint_y=0.12, radius=[15],
        )
        self.inv_button.bind(on_press=self.open_inventory)
        main_layout.add_widget(self.inv_button)

        self.shake_wrapper.add_widget(main_layout)
        self.root_float.add_widget(self.shake_wrapper)

        # --- Слой для частиц и вспышек — поверх всего, не трясётся
        self.particle_layer = FloatLayout(size_hint=(1, 1))
        self.root_float.add_widget(self.particle_layer)

        return self.root_float

    # ---------------------------------------------------------
    #  СЛУЖЕБНЫЕ ОБНОВЛЕНИЯ ГРАФИКИ
    # ---------------------------------------------------------

    def _update_main_bg(self, instance, _value):
        self.main_bg_rect.pos = instance.pos
        self.main_bg_rect.size = instance.size

    def _update_display_rect(self, instance, _value):
        self.display_rect.pos = instance.pos
        self.display_rect.size = instance.size

    # ---------------------------------------------------------
    #  ЛОГИКА РОЛЛА
    # ---------------------------------------------------------

    def on_click(self, _instance):
        if self.click_button.disabled:
            return

        self.score += 1
        self.score_label.text = f"КЛИКОВ: {self.score}"
        self.click_button.disabled = True
        self.click_button.text = "..."
        self.click_button.update_canvas()

        # Roblox-style "прокрутка" редкостей перед финальным результатом —
        # создаёт напряжение и явно показывает, что идёт честный ролл,
        # а не "залипшая" обычная редкость.
        self._flicker_ticks = 0
        self._flicker_max_ticks = 12
        if self._flicker_event is not None:
            self._flicker_event.cancel()
        self._flicker_event = Clock.schedule_interval(self._flicker_step, 0.06)

    def _flicker_step(self, _dt):
        self._flicker_ticks += 1
        name, _, color = random.choice(RARITIES)
        self.drop_label.text = name.upper()
        self.drop_label.color = color
        self.display_bg.rgba = (color[0] * 0.25, color[1] * 0.25, color[2] * 0.25, 1)

        if self._flicker_ticks >= self._flicker_max_ticks:
            self._finalize_roll()
            return False
        return True

    def _roll_rarity_index(self) -> int:
        """Взвешенный ролл с мягкой и жёсткой пити-системой."""
        self.pity_counter += 1

        base_roll = random.randint(1, 10000)
        soft_boost = min(self.pity_counter * SOFT_PITY_STEP, SOFT_PITY_CAP)
        boosted_roll = min(base_roll + soft_boost, 10000)

        if self.pity_counter >= HARD_PITY:
            # Жёсткая гарантия: если долго не было "Редкой" и выше —
            # форсируем результат в диапазон Редкая+.
            floor = RARITIES[RARE_THRESHOLD_INDEX - 1][1] + 1
            boosted_roll = random.randint(floor, 10000)

        rarity_index = 0
        for index, (_name, upper_bound, _color) in enumerate(RARITIES):
            if boosted_roll <= upper_bound:
                rarity_index = index
                break

        if rarity_index >= RARE_THRESHOLD_INDEX:
            self.pity_counter = 0

        return rarity_index

    def _finalize_roll(self):
        rarity_index = self._roll_rarity_index()
        rarity_name, _upper_bound, rarity_color = RARITIES[rarity_index]
        self.inventory[rarity_name] += 1

        self.pity_label.text = f"ПИТИ: {self.pity_counter}/{HARD_PITY}"
        self.pity_bar.value = self.pity_counter

        chance = rarity_chance_percent(rarity_index)
        self.drop_label.opacity = 0
        self.drop_label.color = rarity_color

        if rarity_index == 0:
            self.drop_label.text = "ОБЫЧНАЯ\n[ ничего необычного ]"
            self.display_bg.rgba = (0.12, 0.12, 0.18, 1)
        else:
            self.drop_label.text = (
                f"🎉 ВЫБИТО: {rarity_name.upper()}! 🎉\n[ шанс ~{chance:.2f}% ]"
            )
            self.display_bg.rgba = (
                rarity_color[0] * 0.2, rarity_color[1] * 0.2, rarity_color[2] * 0.2, 1
            )

        # Показываем картинку, если она есть для этой редкости
        image_file = RARITY_IMAGES.get(rarity_name)
        if image_file and os.path.exists(image_file):
            self.drop_image.source = image_file
            self.drop_image.opacity = 0
            self.drop_image.size_hint_y = 0.65
            Animation(opacity=1, duration=0.3).start(self.drop_image)
        else:
            self.drop_image.opacity = 0
            self.drop_image.size_hint_y = 0

        Animation(opacity=1, duration=0.25).start(self.drop_label)

        # Частицы — чем реже редкость, тем их больше
        if rarity_index > 0:
            self._spawn_particles(rarity_color, count=8 + rarity_index * 5)

        # Тряска экрана для топовых редкостей
        if rarity_index >= 5:  # Легендарная и выше
            self._shake_screen()

        # Полноэкранная вспышка для сверхредких
        if rarity_index >= 6:  # Божественная и выше
            self._flash_screen(rarity_color)

        # Небольшая пауза (под анимацию частиц), затем разблокировка кнопки
        cooldown = 0.9 if rarity_index >= 5 else 0.5
        Clock.schedule_once(self._unlock_button, cooldown)

    def _unlock_button(self, _dt):
        self.click_button.disabled = False
        self.click_button.text = "ИСПЫТАТЬ УДАЧУ"
        self.click_button.update_canvas()

    # ---------------------------------------------------------
    #  ЭФФЕКТЫ
    # ---------------------------------------------------------

    def _spawn_particles(self, color, count=12):
        cx, cy = self.display_box.center
        wx, wy = self.display_box.to_window(cx, cy)
        lx, ly = self.particle_layer.to_widget(wx, wy)

        for _ in range(count):
            particle = Particle(color=color)
            particle.center = (lx, ly)
            self.particle_layer.add_widget(particle)

            angle = random.uniform(0, 360)
            distance = random.uniform(dp(60), dp(170))
            dx = distance * math.cos(math.radians(angle))
            dy = distance * math.sin(math.radians(angle))

            anim = Animation(
                x=particle.x + dx, y=particle.y + dy, alpha=0,
                duration=random.uniform(0.55, 0.95), t="out_quad",
            )
            anim.bind(on_complete=lambda *_a, w=particle: self._safe_remove(w))
            anim.start(particle)

    def _flash_screen(self, color):
        flash = FlashOverlay(color=color[:3])
        flash.pos = self.root_float.pos
        flash.size = self.root_float.size
        self.particle_layer.add_widget(flash)
        anim = Animation(alpha=0, duration=0.35, t="out_quad")
        anim.bind(on_complete=lambda *_a: self._safe_remove(flash))
        anim.start(flash)

    def _shake_screen(self):
        offset = dp(14)
        anim = (
            Animation(x=-offset, duration=0.035)
            + Animation(x=offset, duration=0.035)
            + Animation(x=-offset * 0.7, duration=0.035)
            + Animation(x=offset * 0.7, duration=0.035)
            + Animation(x=0, duration=0.035)
        )
        anim.start(self.shake_wrapper)

    def _safe_remove(self, widget):
        if widget.parent is not None:
            widget.parent.remove_widget(widget)

    # ---------------------------------------------------------
    #  ИНВЕНТАРЬ
    # ---------------------------------------------------------

    def open_inventory(self, _instance):
        if self.click_button.disabled:
            return

        inv_layout = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(15))
        inv_layout.bind(minimum_height=inv_layout.setter("height"))
        inv_layout.size_hint_y = None
        inv_layout.height = 0

        total = sum(self.inventory.values()) or 1

        for name, _upper, color in RARITIES:
            count = self.inventory[name]
            percent = (count / total) * 100

            item_box = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(12), 0])
            with item_box.canvas.before:
                Color(0.15, 0.15, 0.22, 1)
                item_rect = RoundedRectangle(pos=item_box.pos, size=item_box.size, radius=[8])

            # Функция-фабрика замыкания — правильный способ синхронизировать
            # RoundedRectangle с виджетом (НЕ .setattr(), а функция setattr()).
            def make_updater(rect):
                def _update(ins, _val):
                    rect.pos = ins.pos
                    rect.size = ins.size
                return _update

            item_box.bind(pos=make_updater(item_rect), size=make_updater(item_rect))

            image_file = RARITY_IMAGES.get(name)
            if image_file and os.path.exists(image_file):
                thumb = KivyImage(
                    source=image_file, size_hint=(None, None),
                    size=(dp(36), dp(36)), allow_stretch=True, keep_ratio=True,
                )
                item_box.add_widget(thumb)

            name_label = Label(
                text=f"• {name.upper()}", color=color, bold=True,
                halign="left", valign="middle", font_size="15sp",
            )
            name_label.bind(size=lambda s, w: setattr(s, "text_size", w))

            count_label = Label(
                text=f"{count} шт. ({percent:.1f}%)", color=(0.65, 0.65, 0.75, 1),
                halign="right", valign="middle", font_size="14sp",
            )
            count_label.bind(size=lambda s, w: setattr(s, "text_size", w))

            item_box.add_widget(name_label)
            item_box.add_widget(count_label)
            inv_layout.add_widget(item_box)

        scroll = ScrollView(size_hint=(1, 0.82))
        scroll.add_widget(inv_layout)

        pity_info = Label(
            text=f"Пити-прогресс: {self.pity_counter}/{HARD_PITY} до гарантии Редкая+",
            font_size="13sp", color=(0.6, 0.6, 0.7, 1), size_hint_y=None, height=dp(24),
        )

        close_button = ModernButton(
            text="ЗАКРЫТЬ ИНВЕНТАРЬ", size_hint_y=0.14, font_size="16sp",
            bold=True, bg_color=(0.8, 0.2, 0.3, 1), radius=[15],
        )

        popup_content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        popup_content.add_widget(pity_info)
        popup_content.add_widget(scroll)
        popup_content.add_widget(close_button)

        popup = Popup(
            title="КОЛЛЕКЦИЯ ВАШИХ РЕДКОСТЕЙ", content=popup_content,
            size_hint=(0.92, 0.85), background_color=(0.07, 0.07, 0.1, 0.95),
        )
        close_button.bind(on_press=popup.dismiss)
        popup.open()


if __name__ == "__main__":
    RngClickerGame().run()
