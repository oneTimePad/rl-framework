from abc import ABCMeta
from abc import abstractmethod
import numpy as np
import attr


""" Elements are utilized for storing information about the agent's interactions
with the environment. They are mostly used for collection information for ReplayBuffers
but can be used on their own as well. Collecting information in this manner is a common
Reinforcement learning paradigm. The internal module used in the attr module. This is wrapped
by theElement class. So the client only has to import one module.
"""

class NumpyElementMixin:
    """ Mixin for a Element that uses Numpy.ndarray
    attrs
    """

    @staticmethod
    def _validate(dtype):
        def valid(instance, attribute, value):
            if not isinstance(value, np.ndarray):
                raise ValueError("%s must be of type np.ndarray"
                                 " but was %s" % (attribute.name, type(value)))
            if not value.dtype == dtype:
                raise ValueError("%s must have dtype %s but had dtype=%s"
                                 % (attribute.name, str(dtype), str(value.dtype)))
        return valid

    @classmethod
    def np_attr(cls, dtype):

        """ Represents a component of a Element that is a np.ndarray """
        return attr.ib(kw_only=True,
                       validator=cls._validate(dtype),
                       metadata={"np_attr" : True})

    @classmethod
    def stack(cls, element_list, normalize_attrs=()):
        """ Combines common np_attrs in the elements in the list
        into one np_attr (stacked np.ndarray)

            Args:
                element_list: list of BufferElement's to reduce
                normalize_attrs: attrs to normalize just in stack

            Returns:
                reduced Element

            Raises:
                ValueError: for missing attrs or fails to stack

        """
        if not hasattr(cls, "make_element_from_dict"):
            raise ValueError("cls must have attribute 'make_element_from_dict'. \
                Sugggestion: subclass Element")

        np_attrs = filter(lambda x: ("np_attr" in x.metadata), list(cls.__attrs_attrs__))
        np_attrs_dict = {x.name: [] for x in np_attrs}

        for element in element_list:
            for name, name_list in np_attrs_dict.items():
                name_list.append(getattr(element, name))

        np_attrs_dict_stacked = {k: np.vstack(v) for k, v in np_attrs_dict.items()}

        if normalize_attrs:
            attrs_to_normalize = filter(lambda x: x.name in normalize_attrs, cls.__attrs_attrs__)

            for attribute in attrs_to_normalize:
                attr_name = attribute.name
                np_attrs_dict_stacked[attr_name] = cls.normalize(np_attrs_dict_stacked[attr_name])

        return cls.make_element_from_dict(np_attrs_dict_stacked)

    @staticmethod
    def normalize(stack, eps=0.01):
        """ Normalize `stacked` element

                Args:
                    stack: stack to normalize
                    eps: min bound for variance

                Returns:
                    normalized stack
        """
        return (stack - stack.mean()) / np.maximum(stack.std(), np.sqrt(eps))




class NormalizingElementMixin:
    """Mixin for a Element that allows for Normalization of some or all
    of it's attributes. A lot RL algorithms utilizing Approximators require
    Normalization of their inputs
    This is for RUNNING Normalization (use NumpyElementMixin for batch-wise normalizing)
    """

    @staticmethod
    def running_variance(sums, sums_sqr, num):
        """Computes running variance from running sum of data,
           running sum of squares of data and data count

            Args:
                sums: running sum of data
                sums_sqr: running sum of square of data
                num: running count of data

            Returns:
                running variance
        """
        variance = (1. / num) * (sums_sqr - ((sums ** 2) / num))
        return variance.astype(np.float32)


    @classmethod
    def make_stats(cls, normalize_attrs=(), **kwargs_to_make_element_zero):
        """ Returns a dictionary of attrs to keep track of for
        normalizing. Used internally by this mixin
            Args:
                normalize_attrs: tuple of str representing which attrs to normalize
                kwargs_to_make_element_zero: args to pass to make_element_zero

            Returns:
                normalizing: dict containg attrs to keep track of

            Raises:
                ValueError: missing attrs, or bad attrs
        """

        if not hasattr(cls, "make_element_zero"):
            raise ValueError("Mixin expects subclass to contain attribute make_element_zero, \
                should subclass Element")



        if not hasattr(cls, "__attrs_attrs__"):
            raise ValueError("Object returned from make_element_zero must have"
                             " attribute __attrs_attrs__, should subclass Element"
                             " and decorated with BufferElement.element")

        normalizing = {}

        if normalize_attrs:
            attrs_to_normalize = filter(lambda x: x.name in normalize_attrs, cls.__attrs_attrs__)

            for attribute in attrs_to_normalize:
                attr_name = attribute.name
                normalizing[attr_name] = (getattr(cls.make_element_zero(**kwargs_to_make_element_zero),
                                                  attr_name),
                                          getattr(cls.make_element_zero(**kwargs_to_make_element_zero),
                                                  attr_name))
        return normalizing

    @staticmethod
    def update_normalize_stats(stats, element):
        """ Updates a stats object with attrs from a new element

                Args:
                    stats: as returned from make_stats
                    element: element to aggregate

                mutates stats
        """

        for attribute_name, stat_tup in stats.items():
            sums, sums_sqr = stat_tup
            value = getattr(element, attribute_name)

            sums_sqr += value ** 2
            sums += value

    @classmethod
    def normalize_element(cls, stats, number_elements, element, eps=0.01):
        """ Normalizes an element based on stats.
                To take advantage of numpy broadcasting, look for
                reduce method in mixins

                Args:
                    stats: as returned from make_stats
                    number_elements: number of elements used to update stats
                    element: element to normalize
                    eps: divide-by-zero protection threshold
        """
        if not hasattr(cls, "make_element_from_dict"):
            raise ValueError("Mixin expects subclass to contain attribute make_element_from_dict, \
                should subclass Element")

        new_attrs_dict = {attribute.name: getattr(element, attribute.name)
                          for attribute in element.__attrs_attrs__}

        for attr_name, stats_tup in stats.items():
            sums, sums_sqr = stats_tup

            variance = cls.running_variance(sums, sums_sqr, number_elements)

            mean = (1. / number_elements) * sums

            value = getattr(element, attr_name)

            normalized_attr = (value - mean) / np.sqrt(np.maximum(variance, eps))

            new_attrs_dict[attr_name] = normalized_attr

        return cls.make_element_from_dict(new_attrs_dict)

class Element(metaclass=ABCMeta):
    """ Represents a type to be placed in a Replay buffer (however, they can be used
    for other purposes as well, and do not require a buffer)
    There purpose is to serve as keepers of steps taken by the agent
    and the associated changes in the environment.
    """

    # decorate sublcass with `Element.element`
    # to set this correctly
    __attrs_attrs__ = []

    @staticmethod
    def element(wrapped_cls):
        """ Wrap attr in Element
                Args:
                    wrapped_cls: cls to decorate
        """
        return attr.s(wrapped_cls, frozen=True)

    def unzip_to_tuple(self):
        """ Puts attributes to tuple

        """
        return tuple((getattr(self, attribute.name) for attribute in self.__attrs_attrs__))

    def unzip_to_dict(self):
        """ Puts attributes in dict
        """
        return {attribute.name: getattr(self, attribute.name) for attribute in self.__attrs_attrs__}


    def deep_copy(self):
        """ Performs deep copy
        of element
        """
        return self.make_element_from_dict(self.unzip_to_dict())

    @classmethod
    def make_element_from_dict(cls, dictionary):
        """ Factory: consructs element from dict of
        corresponding attrs
        """
        return cls.make_element(**dictionary)

    @classmethod
    @abstractmethod
    def make_element_zero(cls, **kwargs):
        """ Factory: Instantiates a 'zeroed' out Element
                **kwargs:
                    arguments specifying extra info
                Returns:
                    instance of 'cls' with 'zeroed' out elements
                        up to the subclass to define what 'zero' means
        """
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def make_element(cls, **kwargs):
        """ Factory: Instantiates a Element of subclass 'cls'
                Up to the subclass how it wants to handle data-sources.
                There just must be at least one 'make' method
                Args:
                    kwargs: specify attrs needed to instantiate

                Returns:
                    instance of 'cls'
        """
        raise NotImplementedError()
