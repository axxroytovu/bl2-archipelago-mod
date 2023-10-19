import unrealsdk
from Mods import ModMenu

class MyMod(ModMenu.SDKMod):
    Name: str = "Archipelago"
    Author: str = "AxxroyTovu"
    Description: str = "Connects BL2 to the Archipelago Multi-World Randomizer System"
    Version: str = "0.0.1"
    SupportedGames: ModMenu.Game = ModMenu.Game.BL2

    def Enable(self) -> None:
        super().Enable()
        unrealsdk.Log("I ARISE!")

    def Disable(self) -> None:
        unrealsdk.Log("I sleep.")
        super().Disable()

instance = MyMod()

ModMenu.RegisterMod(instance)
