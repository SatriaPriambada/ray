from libc.string cimport memcpy
from libc.stdint cimport uintptr_t, uint64_t, INT32_MAX

# This is the default alignment value for len(buffer) < 2048.
DEF kMinorBufferAlign = 8
# This is the default alignment value for len(buffer) >= 2048.
# Some projects like Arrow use it for possible SIMD acceleration.
DEF kMajorBufferAlign = 64
DEF kMajorBufferSize = 2048
DEF kMemcopyDefaultBlocksize = 64
DEF kMemcopyDefaultThreshold = 1024 * 1024

cdef extern from "arrow/util/memory.h" namespace "arrow::internal" nogil:
    void parallel_memcopy(uint8_t* dst, const uint8_t* src, int64_t nbytes,
                          uintptr_t block_size, int num_threads)

cdef extern from "google/protobuf/repeated_field.h" nogil:
    cdef cppclass RepeatedField[Element]:
        const Element* data() const

cdef extern from "ray/protobuf/serialization.pb.h" nogil:
    cdef cppclass CPythonBuffer "ray::serialization::PythonBuffer":
        void set_address(uint64_t value)
        uint64_t address() const
        void set_length(int64_t value)
        int64_t length() const
        void set_itemsize(int64_t value)
        int64_t itemsize()
        void set_ndim(int32_t value)
        int32_t ndim()
        void set_readonly(c_bool value)
        c_bool readonly()
        void set_format(const c_string& value)
        const c_string &format()
        c_string* release_format()
        void add_shape(int64_t value)
        int64_t shape(int index)
        const RepeatedField[int64_t] &shape() const
        int shape_size()
        void add_strides(int64_t value)
        int64_t strides(int index)
        const RepeatedField[int64_t] &strides() const
        int strides_size()

    cdef cppclass CPythonObject "ray::serialization::PythonObject":
        uint64_t inband_data_offset() const
        void set_inband_data_offset(uint64_t value)
        uint64_t inband_data_size() const
        void set_inband_data_size(uint64_t value)
        uint64_t raw_buffers_offset() const
        void set_raw_buffers_offset(uint64_t value)
        uint64_t raw_buffers_size() const
        void set_raw_buffers_size(uint64_t value)
        CPythonBuffer* add_buffer()
        CPythonBuffer& buffer(int index) const
        int buffer_size() const
        size_t ByteSizeLong() const
        int GetCachedSize() const
        uint8_t *SerializeWithCachedSizesToArray(uint8_t *target)
        c_bool ParseFromArray(void* data, int size)


cdef int64_t padded_length(int64_t offset, int64_t alignment):
    return ((offset + alignment - 1) // alignment) * alignment


cdef int64_t padded_length_u64(uint64_t offset, uint64_t alignment):
    return ((offset + alignment - 1) // alignment) * alignment


cdef class SubBuffer:
    cdef:
        void *buf
        Py_ssize_t len
        int readonly
        c_string _format
        int ndim
        c_vector[Py_ssize_t] _shape
        c_vector[Py_ssize_t] _strides
        Py_ssize_t *suboffsets
        Py_ssize_t itemsize
        void *internal
        object buffer

    def __cinit__(self, Buffer buffer):
        # Increase ref count.
        self.buffer = buffer
        self.suboffsets = NULL
        self.internal = NULL

    def __len__(self):
        return self.len // self.itemsize

    @property
    def nbytes(self):
        """
        The buffer size in bytes.
        """
        return self.len

    def tobytes(self):
        """
        Return this buffer as a Python bytes object. Memory is copied.
        """
        return PyBytes_FromStringAndSize(
            <const char*> self.buf, self.len)

    def __getbuffer__(self, Py_buffer* buffer, int flags):
        buffer.readonly = self.readonly
        buffer.buf = self.buf
        buffer.format = <char *>self._format.c_str()
        buffer.internal = self.internal
        buffer.itemsize = self.itemsize
        buffer.len = self.len
        buffer.ndim = self.ndim
        buffer.obj = self  # This is important for GC.
        buffer.shape = self._shape.data()
        buffer.strides = self._strides.data()
        buffer.suboffsets = self.suboffsets

    def __getsegcount__(self, Py_ssize_t *len_out):
        if len_out != NULL:
            len_out[0] = <Py_ssize_t> self.size
        return 1

    def __getreadbuffer__(self, Py_ssize_t idx, void ** p):
        if idx != 0:
            raise SystemError("accessing non-existent buffer segment")
        if p != NULL:
            p[0] = self.buf
        return self.size

    def __getwritebuffer__(self, Py_ssize_t idx, void ** p):
        if idx != 0:
            raise SystemError("accessing non-existent buffer segment")
        if p != NULL:
            p[0] = self.buf
        return self.size


# See 'serialization.proto' for the memory layout in the Plasma buffer.
def unpack_pickle5_buffers(Buffer buf):
    cdef:
        shared_ptr[CBuffer] _buffer = buf.buffer
        const uint8_t *data = buf.buffer.get().Data()
        size_t size = _buffer.get().Size()
        CPythonObject python_object
        CPythonBuffer *buffer_meta
        c_string inband_data
        int64_t protobuf_offset
        int64_t protobuf_size
        int32_t i
        const uint8_t *buffers_segment
    protobuf_offset = (<int64_t*>data)[0]
    if protobuf_offset < 0:
        raise ValueError("The protobuf data offset should be positive."
                         "Got negative instead. "
                         "Maybe the buffer has been corrupted.")
    protobuf_size = (<int64_t*>data)[1]
    if protobuf_size > INT32_MAX or protobuf_size < 0:
        raise ValueError("Incorrect protobuf size. "
                         "Maybe the buffer has been corrupted.")
    if not python_object.ParseFromArray(
            data + protobuf_offset, <int32_t>protobuf_size):
        raise ValueError("Protobuf object is corrupted.")
    inband_data.append(<char*>(data + python_object.inband_data_offset()),
                       <size_t>python_object.inband_data_size())
    buffers_segment = data + python_object.raw_buffers_offset()
    pickled_buffers = []
    # Now read buffer meta
    for i in range(python_object.buffer_size()):
        buffer_meta = <CPythonBuffer *>&python_object.buffer(i)
        buffer = SubBuffer(buf)
        buffer.buf = <void*>(buffers_segment + buffer_meta.address())
        buffer.len = buffer_meta.length()
        buffer.itemsize = buffer_meta.itemsize()
        buffer.readonly = buffer_meta.readonly()
        buffer.ndim = buffer_meta.ndim()
        buffer._format = buffer_meta.format()
        buffer._shape.assign(
          buffer_meta.shape().data(),
          buffer_meta.shape().data() + buffer_meta.ndim())
        buffer._strides.assign(
          buffer_meta.strides().data(),
          buffer_meta.strides().data() + buffer_meta.ndim())
        buffer.internal = NULL
        buffer.suboffsets = NULL
        pickled_buffers.append(buffer)
    return inband_data, pickled_buffers


cdef class Pickle5Writer:
    cdef:
        CPythonObject python_object
        c_vector[Py_buffer] buffers
        # Address of end of the current buffer, relative to the
        # begin offset of our buffers.
        uint64_t _curr_buffer_addr
        uint64_t _protobuf_offset
        int64_t _total_bytes

    def __cinit__(self):
        self._curr_buffer_addr = 0
        self._total_bytes = -1

    def buffer_callback(self, pickle_buffer):
        cdef:
            Py_buffer view
            int32_t i
            CPythonBuffer* buffer = self.python_object.add_buffer()
        cpython.PyObject_GetBuffer(pickle_buffer, &view,
                                   cpython.PyBUF_FULL_RO)
        buffer.set_length(view.len)
        buffer.set_ndim(view.ndim)
        buffer.set_readonly(view.readonly)
        buffer.set_itemsize(view.itemsize)
        if view.format:
            buffer.set_format(view.format)
        if view.shape:
            for i in range(view.ndim):
                buffer.add_shape(view.shape[i])
        if view.strides:
            for i in range(view.ndim):
                buffer.add_strides(view.strides[i])

        # Increase buffer address.
        if view.len < kMajorBufferSize:
            self._curr_buffer_addr = padded_length(
                self._curr_buffer_addr, kMinorBufferAlign)
        else:
            self._curr_buffer_addr = padded_length(
                self._curr_buffer_addr, kMajorBufferAlign)
        buffer.set_address(self._curr_buffer_addr)
        self._curr_buffer_addr += view.len
        self.buffers.push_back(view)

    def get_total_bytes(self, const c_string &inband):
        cdef:
            size_t protobuf_bytes = 0
            uint64_t inband_data_offset = sizeof(int64_t) * 2
            uint64_t raw_buffers_offset = padded_length_u64(
                inband_data_offset + inband.length(), kMajorBufferAlign)
        self.python_object.set_inband_data_offset(inband_data_offset)
        self.python_object.set_inband_data_size(inband.length())
        self.python_object.set_raw_buffers_offset(raw_buffers_offset)
        self.python_object.set_raw_buffers_size(self._curr_buffer_addr)
        # Since calculating the output size is expensive, we will
        # reuse the cached size.
        # So we MUST NOT change 'python_object' afterwards.
        # This is because protobuf could change the output size
        # according to different values.
        protobuf_bytes = self.python_object.ByteSizeLong()
        if protobuf_bytes > INT32_MAX:
            raise ValueError("Total buffer metadata size is bigger than %d. "
                             "Consider reduce the number of buffers "
                             "(number of numpy arrays, etc)." % INT32_MAX)
        self._protobuf_offset = padded_length_u64(
            raw_buffers_offset + self._curr_buffer_addr, kMinorBufferAlign)
        self._total_bytes = self._protobuf_offset + protobuf_bytes
        return self._total_bytes

    cdef void write_to(self, const c_string &inband, shared_ptr[CBuffer] data,
                       int memcopy_threads):
        cdef uint8_t *ptr = data.get().Data()
        cdef int32_t protobuf_size
        cdef uint64_t buffer_addr
        cdef uint64_t buffer_len
        cdef int i
        if self._total_bytes < 0:
            raise ValueError("Must call 'get_total_bytes()' first "
                             "to get the actual size")
        # Write protobuf size for deserialization.
        protobuf_size = self.python_object.GetCachedSize()
        (<int64_t*>ptr)[0] = self._protobuf_offset
        (<int64_t*>ptr)[1] = protobuf_size
        # Write protobuf data.
        self.python_object.SerializeWithCachedSizesToArray(
            ptr + self._protobuf_offset)
        # Write inband data.
        memcpy(ptr + self.python_object.inband_data_offset(),
               inband.data(), inband.length())
        # Write buffer data.
        ptr += self.python_object.raw_buffers_offset()
        for i in range(self.python_object.buffer_size()):
            buffer_addr = self.python_object.buffer(i).address()
            buffer_len = self.python_object.buffer(i).length()
            if (memcopy_threads > 1 and
                    buffer_len > kMemcopyDefaultThreshold):
                parallel_memcopy(ptr + buffer_addr,
                                 <const uint8_t*> self.buffers[i].buf,
                                 buffer_len,
                                 kMemcopyDefaultBlocksize, memcopy_threads)
            else:
                memcpy(ptr + buffer_addr, self.buffers[i].buf, buffer_len)
            # We must release the buffer, or we could experience memory leaks.
            cpython.PyBuffer_Release(&self.buffers[i])
