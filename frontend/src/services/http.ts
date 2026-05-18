import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

http.interceptors.response.use(
  (res) => res.data,
  (err) => Promise.reject(err)
)

export default http
