/* Copyright (c) 2001-2002 The Regents of the University of California
   through E.O. Lawrence Berkeley National Laboratory, subject to
   approval by the U.S. Department of Energy.
   See files COPYRIGHT.txt and LICENSE.txt for further details.

   Revision history:
     2002 Aug: Copy of cctbx/error.h (R.W. Grosse-Kunstleve)
 */

/*! \file
    Declarations and macros for exception handling.
 */

#ifndef SCITBX_ERROR_H
#define SCITBX_ERROR_H

#include <stdio.h>
#include <exception>
#include <string>

#define CheckPoint std::cout << __FILE__ << "(" << __LINE__ << ")" << std::endl << std::flush

//! Common scitbx namespace.
namespace scitbx {

  //! All scitbx exceptions are derived from this class.
  class error : public std::exception
  {
    public:
      //! General scitbx error message.
      error(std::string const& msg) throw()
      {
        msg_ = prefix() + " Error: " + msg;
      }

      //! Error message with file name and line number.
      /*! Used by the macros below.
       */
      error(const char* file, long line, std::string const& msg = "",
            bool Internal = true) throw()
      {
        const char *s = "";
        if (Internal) s = " Internal";
        char buf[64];
        sprintf(buf, "%ld", line);
        msg_ =   prefix() + s + " Error: "
                  + file + "(" + buf + ")";
        if (msg.size()) msg_ += std::string(": ") + msg;
      }

      //! Virtual destructor.
      virtual ~error() throw() {}

      //! Access to the error messages.
      virtual const char* what() const throw()
      {
        return msg_.c_str();
      }

      virtual std::string prefix() const throw()
      {
        return std::string("scitbx");
      }

    protected:
      std::string msg_;
  };

  //! Special class for "Index out of range." exceptions.
  /*! These exceptions are propagated to Python as IndexError.
   */
  class error_index : public error
  {
    public:
      //! Default constructor. The message may be customized.
      explicit
      error_index(std::string const& msg = "Index out of range.") throw()
      : error(msg)
      {}

      //! Virtual destructor.
      virtual ~error_index() throw() {}
  };

} // namespace scitbx

//! For throwing an "Internal Error" exception.
#define SCITBX_INTERNAL_ERROR() scitbx::error(__FILE__, __LINE__)
//! For throwing a "Not implemented" exception.
#define SCITBX_NOT_IMPLEMENTED() scitbx::error(__FILE__, __LINE__, \
             "Not implemented.")
//! Custom scitbx assertion.
#define SCITBX_ASSERT(bool) \
  if (!(bool)) throw scitbx::error(__FILE__, __LINE__,\
    "scitbx_assert(" # bool ") failure.")

#endif // SCITBX_ERROR_H
