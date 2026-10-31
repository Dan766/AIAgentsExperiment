"""Generate a replay that exercises god mode (free: mock agents). Usage: python scripts/make_god_demo.py"""
import asyncio

from driftwood.config import load_scenario
from driftwood.engine import Engine
from driftwood.export import write_export
from driftwood.llm.brain import BrainMock
from driftwood.personas import load_personas
from driftwood.store import Store
from driftwood.world import World


async def main():
    personas = load_personas()
    store = Store(":memory:")
    eng = Engine.start(World.new(load_scenario(), [p.name for p in personas], seed=3), personas, BrainMock(), store,
                       label="god-mode demo (mock agents)")
    eng.inject("rumor", ["Theo"], {"text": "Elliot has been hiding gold behind the wreck."}, at_tick=8)
    eng.inject("supply_drop", params={"items": {"wood": 8, "food": 4}}, at_tick=11)
    eng.inject("storm", params={"severity": 0.4, "energy_loss": 25}, at_tick=16)
    eng.inject("broadcast", params={"text": "Radio: the cyclone is moving faster than forecast."}, at_tick=22)
    eng.inject("whisper", ["Rosa"], {"text": "Check the stockpile after dark."}, at_tick=26)
    await eng.run()
    write_export(store, eng.run_id, "../web/public/god-demo.json")
    print("wrote ../web/public/god-demo.json")


asyncio.run(main())
