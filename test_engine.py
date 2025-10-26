import pygame

# Initialize mixer
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()

# Load engine sound
engine_sound = ('engine_loop.ogg')
engine_sound.set_volume(0.7)

# Play the engine sound
engine_sound.play()

# Keep the program running so you can hear the sound
input("Engine playing. Press Enter to stop...")
