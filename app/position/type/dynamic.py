from position.type.abc.AbstractPositionControl import AbstractPositionControl

class Dynamic(AbstractPositionControl):
    def __init__(self, take_profit, stop_loss, tick_size, symbol, redis_key):
        super().__init__(take_profit, stop_loss, tick_size, symbol, redis_key)

    def execute(self, type, **params):
        return super().check_action(type, **params)
