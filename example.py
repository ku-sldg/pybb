from pybb import BlackboardController, NumberChecker, less_than_3


if __name__ == "__main__":
    controller = BlackboardController()
    controller.register_predicate("less_than_3", less_than_3)
    controller.add_ks(NumberChecker())
    # simulate receiving a measurement
    controller.blackboard.write_entry(
        key="less_than_3",
        predicate="less_than_3",
        measurement=5)
    controller.run()
    print(controller.status())

# TODO: add another partition that is valid/no need repair